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

如果已经完成标定，也可以直接同时显示机械臂基坐标：

```bash
python scripts/vision/detect_realsense_yolo_xyz.py \
  --allow-cpu \
  --calibration-file ./data/calib_run_02/calibration_result.yaml
```

这时画面和终端都会同时输出：

- `camera_xyz_m`
- `base_xyz_m`

### 第 5 步：做标定

先打印并使用仓库里生成的标准 ChArUco 板：

```text
assets/calibration_boards/charuco_11x8_15mm_11mm_dict4x4_50_a4.pdf
```

打印时务必使用 `100%` 比例，关闭 `fit to page`。

采集：

```bash
python scripts/calibration/capture_eye_to_hand.py \
  --channel can0 \
  --board-type charuco \
  --board-cols 11 \
  --board-rows 8 \
  --square-size-mm 15 \
  --marker-size-mm 11 \
  --aruco-dict DICT_4X4_50 \
  --samples 15 \
  --output-dir ./data/calib_run_02

python scripts/calibration/solve_eye_to_hand.py \
  --dataset-dir ./data/calib_run_02

python scripts/calibration/verify_eye_to_hand.py \
  --calibration-file ./data/calib_run_02/calibration_result.yaml \
  --channel can0 \
  --camera-serial 241222074755 \
  --samples 5
```

这一步需要机械臂和相机都在线。

当前这一套标准板和脚本已经验证通过，`calib_run_02` 可作为当前可用标定基线。

### 第 6 步：单独碰机械臂

先 dry-run：

```bash
python scripts/control/move_flange_pose.py \
  --channel can0 \
  --pose -450 0 360 40 45 45 \
  --mm \
  --degrees \
  --send-order mode_target_mode \
  --mode-resend 3
```

确认打印的目标位姿没问题后，再加 `--go`。

说明：

- `move_p` 在这台 NERO 上对可达性很敏感，不是所有笛卡尔位姿都能执行。
- 当前更稳定的发送方式是：
  - `--send-order mode_target_mode`
  - `--mode-resend 3`
- 现在脚本会同时检查平移和姿态误差，不再只看平移。

### 第 7 步：视觉悬停验证

把目标检测结果转成机械臂基坐标，在目标上方固定高度生成悬停位姿：

```bash
DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority \
python scripts/control/hover_detected_target.py \
  --camera-serial 241222074755 \
  --allow-cpu \
  --calibration-file ./data/calib_run_02/calibration_result.yaml
```

说明：

- 默认优先抓取 `bottle`，其次 `cup`
- `cell phone` 会按 `cup` 处理，方便兼容躺倒水杯的误检
- 目标短暂丢失时会保留一段时间继续使用最近一次结果

按键：

- `g`：单次锁定当前目标并发送一次悬停命令
- `f`：切换连续跟随模式
- `q`：退出

真机执行时加 `--go`。连续跟随默认发送上限为 `30Hz`，也可以通过 `--follow-rate-hz` 修改。

### 第 8 步：总控骨架

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
- 已增加标准 ChArUco 生成脚本和可打印板
- 已增加目标悬停脚本 `hover_detected_target.py`
- 已增加笛卡尔可达性探测脚本 `probe_cartesian_reachability.py`
- `detect_realsense_yolo_xyz.py` 已支持同时显示 `camera_xyz` 和 `base_xyz`
- `move_flange_pose.py` 已支持更细的发送顺序调试和姿态误差检查

## 当前仍然保留为占位的部分

- OmniHand 需要安装官方 Python SDK，并在 `hand` 配置里填好开合角度后才能 `--go`
- `run_sort_trash_pipeline.py` 目前是单目标 pick/place 骨架，不是完整生产流程
