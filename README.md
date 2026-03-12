# sort_trash

这个仓库现在适合按“小步验证”推进，不适合一上来追求整套抓取闭环。

建议顺序：

1. 先确认 conda 环境和 Python 依赖
2. 再确认 YOLO 模型和纯视觉推理
3. 再确认 RealSense 取流
4. 再做固定相机标定
5. 最后才接 NERO 和 OmniHand

## 环境初始化

如果需要创建或更新 `grasp-gpu`：

```bash
cd /home/robot/project/sort_trash
bash environment/setup_grasp_gpu.sh
```

这个脚本会：

- 创建或更新 `grasp-gpu`
- 把当前仓库里的 `pyAgxArm` 以 editable 方式安装进去
- 跑一次基础自检

## 当前默认配置

[sort_trash_pipeline.example.yaml](/home/robot/project/sort_trash/config/sort_trash_pipeline.example.yaml) 默认引用的是 [calibration.identity.yaml](/home/robot/project/sort_trash/config/calibration.identity.yaml)。

这只是一个占位标定文件，目的是让你在没有真机、没有真实标定结果时，先把脚本入口、模型加载、配置解析这些基础链路跑通。

只要后面开始碰机械臂，就必须换成真实的 `calibration_result.yaml`。

## 基础自检

不接真机时，先跑：

```bash
cd /home/robot/project/sort_trash
conda run -n grasp-gpu python scripts/dev/check_setup.py \
  --config config/sort_trash_pipeline.example.yaml
```

如果只想额外试加载 YOLO 权重：

```bash
conda run -n grasp-gpu python scripts/dev/check_setup.py \
  --config config/sort_trash_pipeline.example.yaml \
  --try-model
```

如果已经接上 D435，再试：

```bash
conda run -n grasp-gpu python scripts/dev/check_setup.py \
  --config config/sort_trash_pipeline.example.yaml \
  --try-camera
```

## 渐进式联调

### 第 1 步：无硬件自测

```bash
cd /home/robot/project/sort_trash
conda activate grasp-gpu
python scripts/control/run_sort_trash_pipeline.py \
  --config config/sort_trash_pipeline.example.yaml \
  --allow-cpu \
  --self-test
```

这一步完全不需要相机和机械臂。

它会验证：

- 配置文件能否读取
- 占位标定文件能否读取
- YOLO 权重能否加载
- 总控脚本主链路能否完整执行一次

如果这一步通过，再进入相机三步验证。

### 第 2 步：只测 RealSense 取流

```bash
cd /home/robot/project/sort_trash
conda activate grasp-gpu
python scripts/vision/view_realsense_stream.py
```

目标：

- 左侧彩色图正常
- 右侧深度图正常
- 桌面和物体的深度变化可见

### 第 3 步：RealSense + YOLO 2D 检测

```bash
cd /home/robot/project/sort_trash
conda activate grasp-gpu
python scripts/vision/detect_realsense_yolo_2d.py --allow-cpu
```

目标：

- 能识别瓶子、杯子等目标
- 检测框和类别大体正确
- 框中心点大致落在物体上

### 第 4 步：RealSense + YOLO + 深度，输出相机坐标 XYZ

```bash
cd /home/robot/project/sort_trash
conda activate grasp-gpu
python scripts/vision/detect_realsense_yolo_xyz.py --allow-cpu
```

目标：

- 取到检测框中心点
- 取到中心点附近的有效深度
- 输出目标在相机坐标系下的 `X, Y, Z`

说明：

- 这一步还不是手眼标定
- 这一步不需要机械臂在线
- 这一步输出的是“候选抓取点”的相机坐标，不是机械臂基坐标

### 第 5 步：做标定

```bash
python scripts/calibration/capture_eye_to_hand.py \
  --channel can0 \
  --board-cols 8 \
  --board-rows 6 \
  --square-size-mm 20 \
  --samples 15 \
  --output-dir ./data/calib_run_01

python scripts/calibration/solve_eye_to_hand.py \
  --dataset-dir ./data/calib_run_01
```

这一步需要机械臂和相机都在线。

### 第 6 步：单独碰机械臂

先 dry-run：

```bash
python scripts/control/move_flange_pose.py \
  --channel can0 \
  --pose 0.30 0.00 0.20 0.00 0.00 0.00
```

确认打印的目标位姿没问题后，再加 `--go`。

### 第 7 步：总控骨架

先 dry-run：

```bash
python scripts/control/run_sort_trash_pipeline.py \
  --config config/sort_trash_pipeline.example.yaml \
  --allow-cpu
```

真机动作确认后，再加 `--go`。

## 当前已做的仓库修正

- 机械臂相关脚本现在会优先使用当前仓库内的 `pyAgxArm`
- 环境文件已去掉旧的绝对路径依赖
- 已增加总控骨架脚本和示例配置

## 当前仍然保留为占位的部分

- OmniHand 真实开合控制还没接入 SDK
- `run_sort_trash_pipeline.py` 目前是单目标 pick/place 骨架，不是完整生产流程
