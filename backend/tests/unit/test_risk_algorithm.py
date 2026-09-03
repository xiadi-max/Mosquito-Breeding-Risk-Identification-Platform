from app.services.risk_algorithm import RiskPoint, analyze
from app.services.risk_service import describe_mosaic_location


def test_risk_algorithm_empty_points_has_reasonable_empty_output():
    specs,image,peak=analyze([],100,80,20,10,40,75)
    assert specs==[] and peak==0 and image.size==(100,80) and image.mode=="RGBA"
    assert image.getbbox() is None
    image.close()


def test_risk_algorithm_builds_high_hotspot_for_cluster():
    points=[RiskPoint(50+i,50+i,"积水容器") for i in range(5)]
    specs,image,peak=analyze(points,200,150,35,10,30,70)
    assert peak>0 and specs and specs[0].clustering_index>=70
    assert specs[0].clustering_level=="high"
    assert specs[0].dominant_category=="积水容器"
    assert image.mode=="RGBA"
    assert image.getchannel("A").getextrema()[1]>0
    image.close()


def test_risk_threshold_changes_hotspot_boundary_and_overlay():
    points=[RiskPoint(90+i*3,70+i*2,"积水容器") for i in range(8)]
    broad,broad_image,_=analyze(points,240,180,45,10,20,70)
    narrow,narrow_image,_=analyze(points,240,180,45,10,70,90)
    assert broad and narrow and broad[0].area_px2>narrow[0].area_px2
    assert broad_image.getchannel("A").getbbox()!=narrow_image.getchannel("A").getbbox()
    broad_image.close();narrow_image.close()


def test_hotspot_location_uses_plain_mosaic_directions():
    assert describe_mosaic_location(900,600,1000,700)=="拼接图东南部"
    assert describe_mosaic_location(500,350,1000,700)=="拼接图中部"
    assert describe_mosaic_location(100,350,1000,700)=="拼接图西部"
