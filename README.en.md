# sort_trash

English overview for the current `sort_trash` workspace.  
For the full Chinese operating notes, see [README.md](./README.md).

## What This Project Does

This project builds a small closed-loop trash-sorting demo around:

- `NERO` robot arm
- `Intel RealSense D435`
- `YOLO` object detection
- `OmniHand` dexterous hand
- a local web console for non-expert operators

The current practical workflow is:

1. detect a target such as `bottle` or `cup`
2. convert camera coordinates into robot base coordinates
3. move above the target
4. run a fake grasp / release cycle
5. place the object into a recorded drop zone

## Current Working Baseline

Current main calibration:

- `data/calib_run_03/calibration_result.yaml`

Current tuned runtime baseline:

- `hover_height_m = 0.15`
- `grasp_z_offset_m = 0.10`
- `grasp_offset_m = [0.13, 0.0, 0.0]`
- `grasp_rpy_deg = [90.10, -3.89, -1.41]`
- `pose_rpy_deg = [90.10, -3.89, -1.41]`
- `imgsz = 960`
- `rotate_inference_modes = [none, cw90, ccw90]`

## Repository Structure

```text
sort_trash/
├── README.md
├── README.en.md
├── environment/
│   ├── grasp-gpu.yml
│   └── setup_grasp_gpu.sh
├── config/
│   ├── sort_trash_pipeline.example.yaml
│   ├── calibration.identity.yaml
│   ├── task_poses.yaml
│   ├── drop_poses.yaml
│   ├── web_runtime_config.yaml
│   └── robot_workspace.yaml
├── data/
│   └── calib_run_03/
├── assets/
│   └── calibration_boards/
├── docs/
├── scripts/
│   ├── vision/
│   ├── calibration/
│   └── control/
│       ├── _safety.py
│       ├── _web_console_motion.py
│       ├── _web_console_runtime.py
│       ├── hover_detected_target.py
│       ├── run_fake_grasp_cycle.py
│       ├── record_task_poses.py
│       ├── record_drop_poses.py
│       └── web_console_api.py
├── pyAgxArm/
├── webapp/
└── third_party/
```

## Environment Setup

Create or update the `grasp-gpu` conda environment:

```bash
cd /home/robot/project/sort_trash
bash environment/setup_grasp_gpu.sh
```

## Recommended Bring-Up Order

### 1. Basic software check

```bash
cd /home/robot/project/sort_trash
conda run -n grasp-gpu python scripts/dev/check_setup.py \
  --config config/sort_trash_pipeline.example.yaml
```

### 2. RealSense stream only

```bash
cd /home/robot/project/sort_trash
conda activate grasp-gpu
python scripts/vision/view_realsense_stream.py
```

### 3. YOLO 2D detection

```bash
python scripts/vision/detect_realsense_yolo_2d.py --allow-cpu
```

### 4. YOLO + depth + XYZ

```bash
python scripts/vision/detect_realsense_yolo_xyz.py --allow-cpu
```

With calibration:

```bash
python scripts/vision/detect_realsense_yolo_xyz.py \
  --allow-cpu \
  --calibration-file ./data/calib_run_03/calibration_result.yaml
```

### 5. Eye-to-hand calibration

The current ChArUco board configuration is:

- board type: `charuco`
- columns: `11`
- rows: `8`
- square size: `15 mm`
- marker size: `11 mm`
- dictionary: `DICT_4X4_50`

Capture:

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
  --output-dir ./data/calib_run_03
```

Solve:

```bash
python scripts/calibration/solve_eye_to_hand.py \
  --dataset-dir ./data/calib_run_03 \
  --method park
```

Verify:

```bash
python scripts/calibration/verify_eye_to_hand.py \
  --calibration-file ./data/calib_run_03/calibration_result.yaml \
  --channel can0 \
  --camera-serial 241222074755 \
  --samples 5
```

`park` is the current recommended solver for this setup.

## CAN Bring-Up

If `can0` is down:

```bash
cd /home/robot/project/sort_trash/pyAgxArm/pyAgxArm/scripts/ubuntu
sudo bash can_activate.sh can0 1000000
```

Check:

```bash
ip -details link show can0
candump can0
```

## Common Robot Commands

### Hover over a detected target

```bash
cd /home/robot/project/sort_trash
conda activate grasp-gpu
DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority \
python scripts/control/hover_detected_target.py \
  --camera-serial 241222074755 \
  --allow-cpu \
  --calibration-file ./data/calib_run_03/calibration_result.yaml \
  --hover-height-m 0.15 \
  --base-offset-m 0.13 0 0 \
  --pose-rpy-deg 90.10 -3.89 -1.41 \
  --go
```

### Current tuned fake grasp command

```bash
cd /home/robot/project/sort_trash
conda activate grasp-gpu
DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority \
python scripts/control/run_fake_grasp_cycle.py \
  --camera-serial 241222074755 \
  --allow-cpu \
  --calibration-file ./data/calib_run_03/calibration_result.yaml \
  --fps 15 \
  --imgsz 960 \
  --hover-height-m 0.15 \
  --grasp-z-offset-m 0.10 \
  --grasp-offset-m 0.13 0 0 \
  --grasp-rpy-deg 90.10 -3.89 -1.41 \
  --pose-rpy-deg 90.10 -3.89 -1.41 \
  --drop-hover-offset-m 0.10 \
  --drop-z-m 0.15 \
  --rotate-inference-modes none cw90 ccw90 \
  --go
```

## Web Console

The repository now includes:

- a React/Vite frontend in `webapp/`
- a FastAPI backend in `scripts/control/web_console_api.py`

### Backend startup

```bash
cd /home/robot/project/sort_trash
conda activate grasp-gpu
DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority \
python scripts/control/web_console_api.py \
  --camera-serial 241222074755 \
  --allow-cpu \
  --calibration-file ./data/calib_run_03/calibration_result.yaml \
  --fps 15 \
  --imgsz 960 \
  --rotate-inference-modes none cw90 ccw90 \
  --host 0.0.0.0 \
  --port 8000
```

### Frontend startup

```bash
cd /home/robot/project/sort_trash/webapp
export PATH=/home/robot/.local/node-v20.19.0-linux-x64/bin:$PATH
VITE_USE_MOCK=false npm run dev
```

Open:

- `http://localhost:5173/`

### Node.js note

This machine now uses a user-local Node 20 installation:

- `~/.local/node-v20.19.0-linux-x64`

It was added to `~/.bashrc`.  
If your current shell still resolves the old system Node, run:

```bash
export PATH=/home/robot/.local/node-v20.19.0-linux-x64/bin:$PATH
```

### Web console capability scope

Current v1 backend supports:

- status
- detection state
- MJPEG video
- read/write `home/work/standby`
- read/write `bottle/cup`
- runtime config read/write
- move `home/work/standby`
- one fake grasp cycle
- stop current workflow

Real `follow` is still disabled in the web console.

### Unreachable target handling

The web backend now validates whether `target_hover` and `pregrasp_10cm` actually reach the commanded pose.

If the robot clearly fails to reach them:

- fake grasp is aborted
- the hand will not continue to close on that target
- the backend raises `UNREACHABLE_TARGET`
- the frontend shows an “unreachable target” warning and asks for re-detection / retry

## Current Unified Detection Labels

The project maps raw detector labels into these semantic targets:

- `bottle`
- `cup`
- `drink_can`
- `paper`
- `cardboard`
- `plastic_bag`
- `food_waste`
- `other_trash`

The current default active targets for grasping are:

- `bottle`
- `cup`
- `drink_can`

## Notes

- All main motion entry points keep the `z >= 0.10 m` safety rule.
- The web backend was added without modifying the original interactive control scripts.
- If you change the core fake grasp logic in `run_fake_grasp_cycle.py`, you may also need to sync `_web_console_motion.py`.
