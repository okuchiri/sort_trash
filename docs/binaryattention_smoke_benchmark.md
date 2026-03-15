# BinaryAttention Smoke Benchmark

Image: `/root/.cursor/projects/root-dev/assets/c__Users_tangf_AppData_Roaming_Cursor_User_workspaceStorage_3296b6d764a99f4ea75f325fb7d83bc3_images_image-b4e05b4d-bfb7-4963-b67b-df2deaa109b8.png`

| Model | Avg latency (ms) | Top detections |
| --- | ---: | --- |
| YOLO26 baseline | 9.26 | book:0.18 |
| YOLO26 + BinaryAttention prototype | 9.87 | none |

## Notes

- This is a smoke benchmark on one image, not a trained accuracy benchmark.
- The BinaryAttention path uses the experimental local PSA patch and warm-starts from `yolo26s.pt`.
- Latency delta: +0.61 ms
- Relative latency: 1.07x vs baseline
