from __future__ import annotations
import csv, io, json, zipfile
from collections import Counter
from math import hypot
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape
from PIL import Image as PILImage, ImageDraw, ImageFont, ImageOps
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload, sessionmaker
import xlsxwriter
from app.core.config import Settings
from app.core.fingerprint import canonical_json
from app.core.security import resolve_storage_path
from app.core.time import ensure_utc, utc_now
from app.domain.enums import ArtifactKind, ExportStatus, JobStatus
from app.domain.m5_schemas import ExportList, ExportRead
from app.domain.models import Artifact, DecisionVersion, Detection, Export, GridTile, InferenceRun, Job, RiskRun, Task
from app.repositories.m5_repository import M5Repository
from app.services.job_service import JobService
from app.services.mosaic_service import JobExecutionError, _file_metadata


CATEGORY_LABELS={
    "foam box":"泡沫箱","bucket":"水桶","flower pot":"花盆","tire":"轮胎","tyre":"轮胎",
    "water tank":"储水箱","container":"容器","bottle":"瓶罐",
    "potted_plant":"盆栽","green_plants":"绿色植物",
}
CLUSTERING_LEVEL_LABELS={"high":"高聚集","medium":"中聚集"}
DETECTION_STATE_LABELS={"accepted":"已纳入分析","pending":"待人工复核","rejected":"已排除","discarded":"已排除"}


def _category_label(value):
    if not value:return "未分类目标"
    return CATEGORY_LABELS.get(str(value).strip().lower(),str(value))


def _location_label(value):
    return str(value or "未命名区域").replace("重点检查区域","").strip()


def _paragraph(value,style):
    return Paragraph(escape(str(value or "-")).replace("\n","<br/>"),style)


def export_read(item):
    return ExportRead(id=item.id,task_id=item.task_id,format=item.format,risk_run_id=item.risk_run_id,decision_version_id=item.decision_version_id,artifact_id=item.artifact_id,status=item.status,stale=item.status=="stale",created_at=ensure_utc(item.created_at),completed_at=ensure_utc(item.completed_at) if item.completed_at else None,download_url=f"/api/v1/artifacts/{item.artifact_id}/content" if item.artifact_id else None)


class ExportService:
    def __init__(self,session):self.s=session;self.repo=M5Repository(session)
    def list(self,task_id):return ExportList(items=[export_read(i) for i in self.repo.exports(task_id)])


class ExportJobExecutor:
    def __init__(self,factory:sessionmaker[Session],settings:Settings):self.f=factory;self.settings=settings
    def execute(self,job_id,worker_id):
        try:
            snap,data,export_id=self._snapshot(job_id,worker_id)
            self._p(job_id,worker_id,25,"snapshot","已创建可审计数据快照")
            directory=resolve_storage_path(self.settings.resolved_storage_root,f"tasks/{data['task']['id']}/exports/{export_id}");directory.mkdir(parents=True,exist_ok=True)
            fmt=snap["format"];path=directory/{"csv":"detections.csv","xlsx":"statistics.xlsx","pdf":"report.pdf"}[fmt]
            if fmt=="csv":self._csv(path,data,snap["include_detection_details"])
            elif fmt=="xlsx":self._xlsx(path,data,snap["include_detection_details"])
            else:self._pdf(path,data,snap["include_detection_details"])
            self._validate(path,fmt)
            self._p(job_id,worker_id,85,"validate_artifact",f"{fmt.upper()} 文件已通过结构校验")
            return self._persist(job_id,worker_id,export_id,path,fmt,data)
        except Exception:
            with self.f() as s:
                item=s.query(Export).filter(Export.job_id==job_id).one_or_none()
                if item and item.status==ExportStatus.QUEUED.value:item.status=ExportStatus.FAILED.value;s.commit()
            raise

    def _snapshot(self,job_id,worker_id):
        with self.f() as s:
            job=s.get(Job,job_id)
            if job is None or job.worker_id!=worker_id or job.status!=JobStatus.RUNNING.value:raise JobExecutionError("JOB_OWNERSHIP_LOST","Worker 已失去导出作业租约。")
            snap=json.loads(job.input_json);risk=M5Repository(s).risk(job.task_id,snap["risk_run_id"]);item=s.query(Export).filter(Export.job_id==job_id).one_or_none()
            if item is None:raise JobExecutionError("EXPORT_NOT_FOUND","导出记录不存在。")
            if risk is None or risk.status!="current" or risk.input_fingerprint!=snap["risk_fingerprint"]:raise JobExecutionError("EXPORT_INPUT_STALE","风险结果已变化。")
            decision=M5Repository(s).decision(job.task_id,snap["decision_version_id"]) if snap.get("decision_version_id") else None
            if decision and decision.status!="current":raise JobExecutionError("EXPORT_INPUT_STALE","建议版本已变化。")
            task=s.get(Task,job.task_id);run=s.get(InferenceRun,risk.inference_run_id)
            detections=list(s.execute(select(Detection).options(joinedload(Detection.source_grid_tile)).where(Detection.inference_run_id==run.id)).scalars())
            mosaic=risk.inference_run.grid_plan.mosaic_artifact
            density=risk.density_artifact
            data={
                "task":{"id":task.id,"code":task.code,"name":task.name,"area":task.area,"survey_date":task.survey_date.isoformat(),"task_type":task.task_type},
                "risk":{"id":risk.id,"review_snapshot_version":risk.review_snapshot_version,"method":risk.method,"metric":"relative_kde_clustering_index","metric_name":"目标聚集指数","normalization":"current_run_peak","bandwidth_px":risk.bandwidth_px,"resolution_px":risk.resolution_px,"medium_threshold":risk.medium_threshold,"high_threshold":risk.high_threshold,"algorithm_version":risk.algorithm_version,"stats":json.loads(risk.stats_json)},
                "map":{
                    "mosaic_path":str(resolve_storage_path(self.settings.resolved_storage_root,mosaic.relative_path)),
                    "density_path":str(resolve_storage_path(self.settings.resolved_storage_root,density.relative_path)) if density else None,
                    "width":mosaic.width,
                    "height":mosaic.height,
                },
                "hotspots":[{"code":h.code,"name":h.name,"clustering_index":h.clustering_index,"clustering_level":h.clustering_level,"target_count":h.target_count,"dominant_category":h.dominant_category,"polygon":json.loads(h.polygon_pixel_json),"centroid_x":h.centroid_x,"centroid_y":h.centroid_y} for h in sorted(risk.hotspots,key=lambda item:(-item.clustering_index,item.code))],
                "detections":[{"code":d.code,"category":d.class_name,"confidence":d.confidence,"effective_state":d.effective_state,"grid":d.source_grid_tile.code,"center_x":d.center_x,"center_y":d.center_y} for d in detections],
                "decision":json.loads(decision.content_json) if decision else None,
                "decision_meta":{"id":decision.id,"version":decision.version,"source":decision.source,"context":decision.context_text} if decision else None,
                "generated_at":utc_now().isoformat(),
            }
            return snap,data,item.id

    def _csv(self,path,data,include):
        with path.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.writer(f);w.writerow(["检测编号","类别","置信度","有效状态","来源网格","中心X(px)","中心Y(px)"])
            if include:
                for d in data["detections"]:w.writerow([d["code"],d["category"],d["confidence"],d["effective_state"],d["grid"],d["center_x"],d["center_y"]])

    def _xlsx(self,path,data,include):
        wb=xlsxwriter.Workbook(path);header=wb.add_format({"bold":True,"font_color":"white","bg_color":"#166534","border":0,"align":"center"});title=wb.add_format({"bold":True,"font_size":16,"font_color":"#14532D"});sub=wb.add_format({"bold":True,"bg_color":"#DCFCE7"});pct=wb.add_format({"num_format":"0.0%"});num=wb.add_format({"num_format":"0.00"})
        summary=wb.add_worksheet("任务汇总");summary.hide_gridlines(2);summary.write("A1","蚊媒风险分析报告",title);rows=[("任务编号",data["task"]["code"]),("任务名称",data["task"]["name"]),("调查区域",data["task"]["area"]),("调查日期",data["task"]["survey_date"]),("已接受目标",data["risk"]["stats"]["summary"]["accepted_target_count"]),("重点检查区域",len(data["hotspots"])),("中聚集起始",data["risk"]["medium_threshold"]),("高聚集起始",data["risk"]["high_threshold"]),("指标口径","目标聚集指数（本任务 KDE 峰值归一化 0–100，不等同布雷图指数）")];summary.write_row("A3",["指标","值"],header)
        for i,row in enumerate(rows,3):summary.write_row(i,0,row)
        summary.set_column("A:A",20);summary.set_column("B:B",42);summary.freeze_panes(3,0)
        categories=Counter(d["category"] for d in data["detections"] if d["effective_state"]=="accepted");ws=wb.add_worksheet("类别统计");ws.write_row(0,0,["类别","已接受数量"],header)
        for i,(name,count) in enumerate(categories.most_common(),1):ws.write_row(i,0,[name,count]);ws.set_column("A:A",24);ws.set_column("B:B",16)
        hs=wb.add_worksheet("聚集区域");hs.write_row(0,0,["编号","名称","目标聚集指数（0–100）","聚集等级","目标数","主要类别"],header)
        for i,h in enumerate(data["hotspots"],1):hs.write_row(i,0,[h[k] for k in ("code","name","clustering_index","clustering_level","target_count","dominant_category")]);hs.set_column("A:B",20);hs.set_column("C:F",20);hs.freeze_panes(1,0)
        det=wb.add_worksheet("检测明细");det.write_row(0,0,["编号","类别","置信度","有效状态","网格","中心X(px)","中心Y(px)"],header)
        if include:
            for i,d in enumerate(data["detections"],1):det.write_row(i,0,[d[k] for k in ("code","category","confidence","effective_state","grid","center_x","center_y")]);det.write(i,2,d["confidence"],pct)
        det.set_column("A:B",18);det.set_column("C:G",14);det.freeze_panes(1,0);det.autofilter(0,0,max(1,len(data["detections"])),6)
        audit=wb.add_worksheet("审计参数");audit.write_row(0,0,["参数","值"],header);params=[("risk_run_id",data["risk"]["id"]),("review_snapshot_version",data["risk"]["review_snapshot_version"]),("method",data["risk"]["method"]),("metric",data["risk"]["metric"]),("normalization",data["risk"]["normalization"]),("bandwidth_px",data["risk"]["bandwidth_px"]),("resolution_px",data["risk"]["resolution_px"]),("algorithm_version",data["risk"]["algorithm_version"]),("generated_at",data["generated_at"])]
        for i,row in enumerate(params,1):audit.write_row(i,0,row);audit.set_column("A:A",28);audit.set_column("B:B",48)
        wb.close()

    def _font_path(self):
        candidates=[Path(r"C:\Windows\Fonts\msyh.ttc"),Path(r"C:\Windows\Fonts\simsun.ttc"),Path(r"C:\Windows\Fonts\simhei.ttf")]
        for path in candidates:
            if path.is_file():return path
        raise JobExecutionError("PDF_FONT_NOT_CONFIGURED","未找到可嵌入的中文字体。")

    def _font(self):
        font_name="M5Chinese"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name,str(self._font_path())))
            pdfmetrics.registerFontFamily(font_name,normal=font_name,bold=font_name,italic=font_name,boldItalic=font_name)
        return font_name

    def _draw_dashed_line(self,draw,start,end,fill,width,dash,gap):
        x1,y1=start;x2,y2=end;length=hypot(x2-x1,y2-y1)
        if length<=0:return
        ux=(x2-x1)/length;uy=(y2-y1)/length;cursor=0.0
        while cursor<length:
            segment_end=min(length,cursor+dash)
            draw.line((x1+ux*cursor,y1+uy*cursor,x1+ux*segment_end,y1+uy*segment_end),fill=fill,width=width)
            cursor=segment_end+gap

    def _result_map(self,path,data):
        mosaic_path=Path(data["map"]["mosaic_path"])
        density_path=Path(data["map"]["density_path"]) if data["map"].get("density_path") else None
        if not mosaic_path.is_file():raise JobExecutionError("PDF_MAP_SOURCE_MISSING","报告缺少拼接底图，无法生成区域定位图。")
        with PILImage.open(mosaic_path) as source:
            source=ImageOps.exif_transpose(source).convert("RGBA")
            original_width,original_height=source.size
            scale=min(1.0,1800/max(1,original_width),1200/max(1,original_height))
            size=(max(1,round(original_width*scale)),max(1,round(original_height*scale)))
            canvas=source.resize(size,PILImage.Resampling.LANCZOS) if source.size!=size else source.copy()
        if density_path and density_path.is_file():
            with PILImage.open(density_path) as density_source:
                density=density_source.convert("RGBA").resize(canvas.size,PILImage.Resampling.BILINEAR)
                canvas=PILImage.alpha_composite(canvas,density)
        draw=ImageDraw.Draw(canvas,"RGBA");width,height=canvas.size
        label_font=ImageFont.truetype(str(self._font_path()),max(17,round(width/50)))
        note_font=ImageFont.truetype(str(self._font_path()),max(14,round(width/65)))
        line_width=max(3,round(width/260));dash=max(10,round(width/70));gap=max(7,round(width/110))
        for hotspot in data["hotspots"]:
            points=[(float(x)*scale,float(y)*scale) for x,y in hotspot.get("polygon",[])]
            if len(points)>=2:
                if points[0]!=points[-1]:points.append(points[0])
                for start,end in zip(points,points[1:]):
                    self._draw_dashed_line(draw,start,end,(4,19,25,210),line_width+3,dash,gap)
                    self._draw_dashed_line(draw,start,end,(255,255,255,245),line_width,dash,gap)
            level=CLUSTERING_LEVEL_LABELS.get(hotspot["clustering_level"],hotspot["clustering_level"])
            label=f"{hotspot['code']}  {level}  指数 {hotspot['clustering_index']}/100  {hotspot['target_count']} 个目标"
            box=draw.textbbox((0,0),label,font=label_font,stroke_width=1);text_width=box[2]-box[0];text_height=box[3]-box[1]
            anchor_x=(min((point[0] for point in points),default=hotspot["centroid_x"]*scale)+12)
            anchor_y=(min((point[1] for point in points),default=hotspot["centroid_y"]*scale)+12)
            x=min(max(10,anchor_x),max(10,width-text_width-34));y=min(max(10,anchor_y),max(10,height-text_height-34))
            draw.rounded_rectangle((x-10,y-8,x+text_width+12,y+text_height+12),radius=8,fill=(4,24,31,225),outline=(105,226,204,245),width=2)
            draw.text((x,y),label,font=label_font,fill=(255,255,255,255),stroke_width=1,stroke_fill=(0,0,0,180))
        legend_lines=[
            "白色虚线：重点检查区域的大致范围（不是建筑或行政边界）",
            "聚集颜色：由蓝绿到黄红表示本任务内目标由较分散到较集中",
        ]
        legend_width=max(draw.textbbox((0,0),line,font=note_font)[2] for line in legend_lines)+34
        legend_height=(note_font.size+9)*len(legend_lines)+20
        lx=18;ly=max(18,height-legend_height-18)
        draw.rounded_rectangle((lx,ly,lx+min(legend_width,width-36),ly+legend_height),radius=10,fill=(4,24,31,225),outline=(105,226,204,230),width=2)
        for index,line in enumerate(legend_lines):draw.text((lx+16,ly+12+index*(note_font.size+9)),line,font=note_font,fill=(238,249,247,255))
        canvas.convert("RGB").save(path,"PNG",optimize=True)
        canvas.close()

    def _decision_action(self,data,hotspot):
        decision=data.get("decision") or {}
        priority=next((item for item in decision.get("priorities",[]) if item.get("hotspot_code")==hotspot["code"]),None)
        if priority:
            paragraphs=[part.strip() for part in str(priority.get("body") or "").split("\n\n") if part.strip()]
            readable=[part.split("：",1)[-1].strip() for part in paragraphs if part.startswith(("现场信息：","处置建议："))]
            if readable:return " ".join(readable)
        return f"到结果图中 {hotspot['code']} 标记区域，核查积水及幼虫或蛹情况；发现积水立即清除并记录，雨后安排复查。"

    def _pdf(self,path,data,include):
        font=self._font();styles=getSampleStyleSheet()
        normal=ParagraphStyle("CN",parent=styles["BodyText"],fontName=font,fontSize=9,leading=14,textColor=colors.HexColor("#17323A"),spaceAfter=2*mm)
        small=ParagraphStyle("CNSmall",parent=normal,fontSize=7.5,leading=11,textColor=colors.HexColor("#52666D"),spaceAfter=1*mm)
        table_head=ParagraphStyle("CNTableHead",parent=small,textColor=colors.white,spaceAfter=0)
        heading=ParagraphStyle("CNH",parent=styles["Heading1"],fontName=font,fontSize=18,leading=23,textColor=colors.HexColor("#0F5F50"),alignment=TA_CENTER,spaceAfter=4*mm)
        subtitle=ParagraphStyle("CNSub",parent=normal,fontSize=10,leading=15,textColor=colors.HexColor("#52666D"),alignment=TA_CENTER,spaceAfter=4*mm)
        h2=ParagraphStyle("CNH2",parent=styles["Heading2"],fontName=font,fontSize=13,leading=18,textColor=colors.HexColor("#0F6B58"),spaceBefore=2*mm,spaceAfter=3*mm)
        h3=ParagraphStyle("CNH3",parent=normal,fontSize=10.5,leading=16,textColor=colors.HexColor("#0F5F50"),spaceAfter=1.5*mm)
        doc=SimpleDocTemplate(str(path),pagesize=A4,rightMargin=16*mm,leftMargin=16*mm,topMargin=14*mm,bottomMargin=15*mm,title="蚊媒潜在孳生地巡查报告",author="蚊媒识别工作台")
        map_path=path.with_name("report-map.png");self._result_map(map_path,data)
        accepted=data["risk"]["stats"]["summary"]["accepted_target_count"];hotspot_count=len(data["hotspots"])
        if hotspot_count:
            lead=data["hotspots"][0]
            summary=f"本次有 {accepted} 个经人工复核后纳入分析的潜在孳生容器，形成 {hotspot_count} 处重点检查区域。建议先到结果图中 {lead['code']} 标记区域核查。该结果表示“需要现场确认”，不表示已经发现蚊虫或发生疫情。"
        else:
            summary=f"本次有 {accepted} 个经人工复核后纳入分析的潜在孳生容器，但没有形成达到当前分界的重点检查区域。建议结合降雨和现场情况保持常规巡查。"
        task_table=Table([
            [_paragraph("任务编号",small),_paragraph(data["task"]["code"],normal),_paragraph("巡查日期",small),_paragraph(data["task"]["survey_date"],normal)],
            [_paragraph("任务名称",small),_paragraph(data["task"]["name"],normal),_paragraph("巡查区域",small),_paragraph(data["task"]["area"],normal)],
        ],colWidths=[20*mm,63*mm,20*mm,63*mm],style=TableStyle([("BACKGROUND",(0,0),(0,-1),colors.HexColor("#E8F7F2")),("BACKGROUND",(2,0),(2,-1),colors.HexColor("#E8F7F2")),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#A7C9C0")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        summary_box=Table([[_paragraph(summary,ParagraphStyle("Summary",parent=normal,fontSize=10.5,leading=17,textColor=colors.HexColor("#0B453A"),spaceAfter=0))]],colWidths=[166*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#EAF8F4")),("BOX",(0,0),(-1,-1),.8,colors.HexColor("#5FB9A6")),("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
        report_image=RLImage(str(map_path));image_width=166*mm;image_height=image_width*report_image.imageHeight/report_image.imageWidth
        if image_height>103*mm:image_height=103*mm;image_width=image_height*report_image.imageWidth/report_image.imageHeight
        report_image.drawWidth=image_width;report_image.drawHeight=image_height;report_image.hAlign="CENTER"
        marker_help=Table([
            [_paragraph("区域编号",h3),_paragraph("H01 为本次自动编号的第 1 处重点检查区域。系统先按目标聚集指数从高到低编号，指数相同时再按拼接图从北到南、从西到东排序。编号用于对应地图、表格和处置建议，重新分析后可能变化。",normal)],
            [_paragraph("边界含义",h3),_paragraph("白色虚线标示达到当前聚集指数分界、且彼此相连范围的近似外包边界，不代表单个目标框、屋顶边界或行政边界。虚线为当前显示方式，报告也可使用其他醒目标记定位区域。",normal)],
            [_paragraph("指标口径",h3),_paragraph(f"目标聚集指数表示本任务内部的相对聚集强弱。中聚集从 {data['risk']['medium_threshold']} 开始，高聚集从 {data['risk']['high_threshold']} 开始。该指数不代表积水概率、蚊虫阳性率或疫情概率。",normal)],
        ],colWidths=[34*mm,132*mm],style=TableStyle([("BACKGROUND",(0,0),(0,-1),colors.HexColor("#F2F7F6")),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#C7D9D4")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        story=[Paragraph("蚊媒潜在孳生地巡查报告",heading),Paragraph("用于安排现场核查与积水清理，不作为疫情诊断结论",subtitle),task_table,Spacer(1,4*mm),summary_box,Spacer(1,4*mm),Paragraph("重点检查区域定位图",h2),report_image,Spacer(1,2*mm),_paragraph("图 1  拼接影像、目标聚集颜色与重点检查区域编号。报告中的 H01、H02 等编号均以本图为准。",small),Spacer(1,2*mm),marker_help,PageBreak(),Paragraph("重点检查区域与处置顺序",h2)]
        hotrows=[[_paragraph(value,table_head) for value in ("区域编号","图上位置","聚集程度","目标聚集指数","复核目标","主要识别类别")]]
        for hotspot in data["hotspots"]:
            hotrows.append([_paragraph(hotspot["code"],normal),_paragraph(_location_label(hotspot["name"]),normal),_paragraph(CLUSTERING_LEVEL_LABELS.get(hotspot["clustering_level"],hotspot["clustering_level"]),normal),_paragraph(f"{hotspot['clustering_index']}/100",normal),_paragraph(f"{hotspot['target_count']} 个",normal),_paragraph(_category_label(hotspot["dominant_category"]),normal)])
        if len(hotrows)==1:hotrows.append([_paragraph("-",normal),_paragraph("当前没有形成重点检查区域",normal),_paragraph("-",normal),_paragraph("-",normal),_paragraph("0 个",normal),_paragraph("-",normal)])
        story.append(Table(hotrows,colWidths=[20*mm,38*mm,25*mm,29*mm,22*mm,32*mm],repeatRows=1,style=TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0F6B58")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#B6CBC5")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)])))
        story.extend([Spacer(1,4*mm),Paragraph("现场处置建议",h2)])
        for hotspot in data["hotspots"]:
            level=CLUSTERING_LEVEL_LABELS.get(hotspot["clustering_level"],hotspot["clustering_level"]);priority="优先核查" if hotspot["clustering_level"]=="high" else "近期核查"
            why=f"{hotspot['code']} 位于{_location_label(hotspot['name'])}，目标聚集指数为 {hotspot['clustering_index']}/100（{level}），区域内有 {hotspot['target_count']} 个经人工复核后纳入分析的{_category_label(hotspot['dominant_category'])}。"
            action=self._decision_action(data,hotspot)
            card=Table([[_paragraph(f"{priority} {hotspot['code']}",h3)],[ _paragraph(f"关注依据：{why}\n现场处置：{action}",normal)]],colWidths=[166*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#FFF1EF") if hotspot["clustering_level"]=="high" else colors.HexColor("#FFF8E7")),("BOX",(0,0),(-1,-1),.5,colors.HexColor("#D79A83") if hotspot["clustering_level"]=="high" else colors.HexColor("#D9B75F")),("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
            story.extend([KeepTogether([card,Spacer(1,2.5*mm)])])
        if not data["hotspots"]:story.append(_paragraph("当前没有需要单独编号的重点检查区域。请按既定计划开展常规巡查，并在连续降雨后复查。",normal))
        checklist=[[ _paragraph("现场核查记录（可打印后勾选）",h3),""],[_paragraph("□ 积水情况已核查",normal),_paragraph("□ 幼虫或蛹情况已核查",normal)],[_paragraph("□ 积水容器已清除或倒置",normal),_paragraph("□ 现场照片已留存并安排复查",normal)]]
        story.extend([Spacer(1,3*mm),Table(checklist,colWidths=[83*mm,83*mm],style=TableStyle([("SPAN",(0,0),(1,0)),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EAF8F4")),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#B6CBC5")),("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))])
        if include:
            story.extend([Spacer(1,5*mm),Paragraph("识别结果明细",h2),_paragraph("模型置信度只表示模型对“物体类别”的识别把握，不表示容器有积水、存在蚊幼虫或传播疾病的概率。",small)])
            rows=[[_paragraph(value,table_head) for value in ("目标编号","识别类别","模型置信度","人工复核状态","来源图块")]]
            rows.extend([_paragraph(value,normal) for value in (d["code"],_category_label(d["category"]),f"{d['confidence']:.1%}",DETECTION_STATE_LABELS.get(d["effective_state"],d["effective_state"]),d["grid"])] for d in data["detections"])
            story.append(Table(rows,colWidths=[26*mm,42*mm,30*mm,38*mm,30*mm],repeatRows=1,style=TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0F6B58")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#C2D2CE")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)])))
        generated=str(data["generated_at"]).replace("T"," ").replace("+00:00"," UTC")
        trace_rows=[[_paragraph("分析批次号",small),_paragraph(data["risk"]["id"],small)],[_paragraph("分析方法",small),_paragraph(f"KDE 目标聚集分析（{data['risk']['algorithm_version']}）",small)],[_paragraph("人工复核版本",small),_paragraph(data["risk"]["review_snapshot_version"],small)],[_paragraph("报告生成时间",small),_paragraph(generated,small)]]
        story.extend([Spacer(1,5*mm),Paragraph("技术追溯信息",h2),_paragraph("以下信息仅供问题追踪和结果复现，日常现场处置无需解读。",small),Table(trace_rows,colWidths=[34*mm,132*mm],style=TableStyle([("BACKGROUND",(0,0),(0,-1),colors.HexColor("#F2F7F6")),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#CDDAD7")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)])),Spacer(1,4*mm),Table([[_paragraph("重要说明：系统识别的是潜在孳生容器和相对聚集位置，仅用于辅助安排现场核查。是否存在积水、蚊幼虫以及是否需要采取公共卫生措施，应由现场检查和疾控专业人员确认。",small)]],colWidths=[166*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#F5F7F7")),("BOX",(0,0),(-1,-1),.4,colors.HexColor("#BFCBC8")),("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))])
        def footer(pdf_canvas,pdf_doc):
            pdf_canvas.saveState();pdf_canvas.setStrokeColor(colors.HexColor("#C7D6D2"));pdf_canvas.setLineWidth(.4);pdf_canvas.line(pdf_doc.leftMargin,10*mm,A4[0]-pdf_doc.rightMargin,10*mm);pdf_canvas.setFont(font,7);pdf_canvas.setFillColor(colors.HexColor("#6B7E83"));pdf_canvas.drawString(pdf_doc.leftMargin,6.5*mm,f"任务 {data['task']['code']} · 蚊媒潜在孳生地巡查报告");pdf_canvas.drawRightString(A4[0]-pdf_doc.rightMargin,6.5*mm,f"第 {pdf_doc.page} 页");pdf_canvas.restoreState()
        try:doc.build(story,onFirstPage=footer,onLaterPages=footer)
        finally:map_path.unlink(missing_ok=True)

    def _validate(self,path,fmt):
        if not path.is_file() or path.stat().st_size<10:raise JobExecutionError("EXPORT_VALIDATION_FAILED","导出文件为空。")
        if fmt=="csv":
            if not path.read_bytes().startswith(b"\xef\xbb\xbf"):raise JobExecutionError("EXPORT_VALIDATION_FAILED","CSV 缺少 UTF-8 BOM。")
        elif fmt=="xlsx":
            with zipfile.ZipFile(path) as z:
                names=set(z.namelist())
                if "xl/workbook.xml" not in names or "xl/worksheets/sheet1.xml" not in names:raise JobExecutionError("EXPORT_VALIDATION_FAILED","XLSX 结构无效。")
        else:
            reader=PdfReader(str(path))
            has_map=any(
                any(obj.get_object().get("/Subtype")=="/Image" for obj in ((page.get("/Resources") or {}).get("/XObject") or {}).values())
                for page in reader.pages
            )
            if len(reader.pages)<1 or path.stat().st_size<1000:raise JobExecutionError("EXPORT_VALIDATION_FAILED","PDF 页数或文件大小无效。")
            if not has_map:raise JobExecutionError("EXPORT_VALIDATION_FAILED","PDF 缺少重点检查区域定位图。")

    def _persist(self,job_id,worker_id,export_id,path,fmt,data):
        sha,size=_file_metadata(path);artifact_id=str(uuid4());kind={"csv":ArtifactKind.CSV.value,"xlsx":ArtifactKind.XLSX.value,"pdf":ArtifactKind.PDF.value}[fmt]
        with self.f() as s:
            job=s.get(Job,job_id);item=s.get(Export,export_id)
            if job is None or job.worker_id!=worker_id or item is None:raise JobExecutionError("JOB_OWNERSHIP_LOST","提交导出结果前失去租约。")
            artifact=Artifact(id=artifact_id,task_id=job.task_id,job_id=job_id,kind=kind,relative_path=path.relative_to(self.settings.resolved_storage_root).as_posix(),sha256=sha,size_bytes=size,mime_type={"csv":"text/csv; charset=utf-8","xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","pdf":"application/pdf"}[fmt],metadata_json=canonical_json({"risk_run_id":item.risk_run_id,"decision_version_id":item.decision_version_id}),is_current=True,created_at=utc_now());s.add(artifact);item.artifact_id=artifact_id;item.status=ExportStatus.READY.value;item.completed_at=utc_now();s.flush();result={"export_id":item.id,"artifact_id":artifact_id,"format":fmt,"download_url":f"/api/v1/artifacts/{artifact_id}/content"};JobService(s,self.settings).succeed(job_id,worker_id,result);return result
    def _p(self,*a):
        with self.f() as s:JobService(s,self.settings).report_progress(a[0],a[1],progress=a[2],step=a[3],message=a[4])
