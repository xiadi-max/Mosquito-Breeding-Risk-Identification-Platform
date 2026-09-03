# OpenCV 拼接简单验证

## 1. 安装并进入环境

打开 Anaconda Prompt：

```bat
conda activate mosquito311
cd /d E:\vibecoding\蚊媒识别\codex-v2\v2.2\backend
python -m pip install -e ".[dev]"
```

## 2. 一条命令验证最新样例

```bat
python scripts\validate_opencv_mosaic.py --input-dir "E:\图像识别\预处理-图像拼接-hzz\拼接"
```

成功时最后应看到：

```text
OpenCV SCANS validation passed
Sources: 6
Dimensions: 4839 x 2722
Strategy: opencv_scans_affine
```

打开下面的文件目视检查：

```text
E:\vibecoding\蚊媒识别\codex-v2\v2.2\backend\data\opencv-validation\mosaic.jpg
```

应满足：

- 6 张图形成一张连续区域图；
- 外围没有大块纯黑边；
- 没有明显断层、双影或错位；
- 亮度和接缝过渡自然；
- 输出尺寸为 `4839 × 2722`。

## 3. 运行完整自动测试

```bat
python -m pytest -q
```

全部显示 `passed` 即可。

## 4. 在网页中验证

确认 `.env` 包含：

```dotenv
MOSAIC_PROVIDER=opencv
MOSAIC_WORK_SCALE=0.6
MOSAIC_PANO_CONFIDENCE_THRESHOLD=0.3
MOSAIC_BLACK_BORDER_THRESHOLD=2
MOSAIC_OUTPUT_JPEG_QUALITY=95
```

启动：

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_m6.ps1
```

浏览器打开 `http://127.0.0.1:8000/`，新建任务，上传至少 2 张同一区域 JPG/PNG，然后点击“开始自动拼接”。成功后页面应显示真实拼接预览、`SCANS 仿射`、工作尺度 `0.6` 和原生输出尺寸。
