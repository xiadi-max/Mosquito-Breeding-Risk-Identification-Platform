from __future__ import annotations
import math
from collections import Counter, deque
from dataclasses import dataclass
from PIL import Image


@dataclass(frozen=True, slots=True)
class RiskPoint:
    x: float; y: float; category: str


@dataclass(frozen=True, slots=True)
class HotspotSpec:
    clustering_index: int; clustering_level: str; target_count: int; dominant_category: str | None
    polygon: list[list[float]]; centroid_x: float; centroid_y: float; area_px2: float


def analyze(points, width, height, bandwidth, resolution, medium, high):
    cols=max(1, math.ceil(width/resolution)); rows=max(1, math.ceil(height/resolution))
    values=[[0.0]*cols for _ in range(rows)]
    for gy in range(rows):
        cy=(gy+.5)*resolution
        for gx in range(cols):
            cx=(gx+.5)*resolution
            values[gy][gx]=sum(math.exp(-((cx-p.x)**2+(cy-p.y)**2)/(2*bandwidth**2)) for p in points)
    peak=max((v for row in values for v in row), default=0.0)
    scores=[[round(v/peak*100) if peak else 0 for v in row] for row in values]
    seen=set(); specs=[]
    for y in range(rows):
        for x in range(cols):
            if (x,y) in seen or scores[y][x] < medium: continue
            queue=deque([(x,y)]); seen.add((x,y)); cells=[]
            while queue:
                cx,cy=queue.popleft(); cells.append((cx,cy))
                for nx,ny in ((cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)):
                    if 0<=nx<cols and 0<=ny<rows and (nx,ny) not in seen and scores[ny][nx]>=medium:
                        seen.add((nx,ny)); queue.append((nx,ny))
            minx=min(c[0] for c in cells)*resolution; miny=min(c[1] for c in cells)*resolution
            maxx=min(width,(max(c[0] for c in cells)+1)*resolution); maxy=min(height,(max(c[1] for c in cells)+1)*resolution)
            inside=[p for p in points if minx<=p.x<=maxx and miny<=p.y<=maxy]
            categories=Counter(p.category for p in inside)
            clustering_index=max(scores[cy][cx] for cx,cy in cells)
            specs.append(HotspotSpec(clustering_index,"high" if clustering_index>=high else "medium",len(inside),categories.most_common(1)[0][0] if categories else None,
                [[minx,miny],[maxx,miny],[maxx,maxy],[minx,maxy],[minx,miny]],(minx+maxx)/2,(miny+maxy)/2,(maxx-minx)*(maxy-miny)))
    # Produce a transparent overlay instead of an opaque false-colour bitmap.
    # Pixels below the selected medium threshold must reveal the real mosaic;
    # this also makes threshold changes visible on the map after recomputation.
    image=Image.new("RGBA",(cols,rows),(0,0,0,0)); pixels=image.load()
    for y,row in enumerate(scores):
        for x,score in enumerate(row):
            if score < medium:
                continue
            if score >= high:
                ratio=(score-high)/max(1,100-high)
                red,green,blue=255,round(126*(1-ratio)),round(74*(1-ratio))
            else:
                ratio=(score-medium)/max(1,high-medium)
                red=round(67+(255-67)*ratio)
                green=round(216+(191-216)*ratio)
                blue=round(179+(91-179)*ratio)
            alpha=round(70+170*(score-medium)/max(1,100-medium))
            pixels[x,y]=(red,green,blue,min(240,max(70,alpha)))
    image=image.resize((width,height), Image.Resampling.BILINEAR)
    return specs, image, peak
