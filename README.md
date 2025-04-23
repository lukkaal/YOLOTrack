# ROS2 Yolov5 + BodyControlNode 联动笔记整理

## 1. 等待依赖服务

```python
self.client = self.create_client(Trigger, '/controller_manager/init_finish')
self.client.wait_for_service()
self.client = self.create_client(Trigger, '/yolov5/start')
self.client.wait_for_service()
```

- `BodyControlNode` 首先等待 `/controller_manager/init_finish`，确保机械臂就绪。
- 然后等待 `/yolov5/start` 服务上线，确保 `Yolov5Node` 已经创建了服务端（开启服务）。

## 2. 触发 YOLO 开始检测

```python
self.future = self.client.call_async(Trigger.Request())  # 调用 /yolov5/start
rclpy.spin_until_future_complete(self, self.future)
```

- `BodyControlNode` 作为客户端发送空的 `Trigger` 请求到 `/yolov5/start`。
- `Yolov5Node` 的 `start_srv_callback` 被触发，将内部 `self.start = True`，开始发布检测结果。

## 3. 话题层面的联动

| 发布者              | 话题                        | 消息类型                    | 订阅者                        |
|---------------------|-----------------------------|-----------------------------|-------------------------------|
| Yolov5Node          | `/yolov5/object_detect`     | `interfaces/msg/ObjectsInfo`| `BodyControlNode`（`get_object_callback`）|
| Yolov5Node          | `/yolov5/object_image`      | `sensor_msgs/msg/Image`     | `BodyControlNode`（`image_callback`）     |
| BodyControlNode（相机） | `/depth_cam/depth/image_raw` | `sensor_msgs/msg/Image`     | `BodyControlNode`（`depth_image_callback`）|

### Yolov5Node 发布

当 `start=True` 时，`image_proc` 每帧发布两种消息：

- `ObjectsInfo`：检测到的目标（如人）的 `box`、`score`、`class_name` 列表
- 带框的 `Image`：用于实时可视化

### BodyControlNode 订阅

- `/yolov5/object_detect` → `get_object_callback`：提取第一个 `class_name == 'person'` 的框中心，用于追踪和测距
- `/yolov5/object_image` → `image_callback`：获取彩色画面流，用于可视化和键盘中断监测
- `/depth_cam/depth/image_raw` → `depth_image_callback`：获取深度图，用于计算 ROI 区域平均深度

---

- **服务 `/yolov5/start`**：`BodyControlNode` 调用，通知 `Yolov5Node` 开始检测并发布
- **话题 `/yolov5/object_detect` 和 `/yolov5/object_image`**：`Yolov5Node` 发布检测结果，`BodyControlNode` 订阅处理

两个节点形成“**先服务初始化 → 实时数据流 → 控制命令 → 驱动机器**”的闭环。

## 4. 后台线程处理图像流程

```python
threading.Thread(target=self.main, daemon=True).start()
```

新线程用于从图像队列独立处理视觉控制流程，与 ROS2 回调机制解耦：

- 同时监听图像和深度输入
- 后台进行目标跟踪与底盘控制
- 并发处理不卡主线程

### `image_proc()` 工作流程：

- 根据检测到的人目标，在图像上画圈并框出目标
- 使用对应 ROI 的深度值计算平均深度
- 调用 PID 控制计算 `linear.x` 和 `angular.z`
- 发布控制命令到 `/controller/cmd_vel`

---

## 5. Ctrl+C 优雅退出流程

- **主线程**：
  - 收到 `SIGINT` 后退出 `rclpy.spin()`，执行 `destroy_node()` 和 `rclpy.shutdown()`
- **后台线程**：
  - `SIGINT` 被 Python 捕捉，置 `self.running = False`
  - `while self.running:` 循环结束，线程自然退出（因 `daemon=True`，主线程退出进程也结束）

---

## 6. 不同线程的分工

### ROS 初始化与构造

- 在 `BodyControlNode.__init__()` 中调用 `rclpy.init()`，创建订阅者、发布者、服务端/客户端等
- 同步等待 `/yolov5/start` 服务，触发检测启动

### 1. 主线程（ROS 事件循环）

- 使用 `rclpy.spin()` 启动单线程 Executor，循环监听分发：

  - `image_callback`：图像入队
  - `depth_image_callback`：保存深度图
  - `get_object_callback`：记录检测到的中心点

- `get_node_state` 服务用于检查节点是否就绪
- 主线程不处理重量级计算，仅做回调分发

- 当 `Ctrl+C` 触发 `SIGINT`，退出 `spin()` → `destroy_node()` → `rclpy.shutdown()`

### 2. 背景线程（Worker）

- 从 `self.image_queue` 中抓帧，执行完整视觉控制逻辑

#### 图像处理步骤：

- 在图像中画出检测目标
- 读取对应 ROI 的深度值
- 使用 PID 控制器生成运动指令 `Twist`
- 发布到底盘控制话题 `/controller/cmd_vel`

#### 退出检测：

- 检测到键盘 `'q'` 或 `ESC` 时置 `self.running=False`，跳出循环

---

## 7. 后台线程中调用 `rclpy.shutdown()` 的原因

双重退出保护机制：

- 主线程中的 `rclpy.spin()` 正常结束时调用 `rclpy.shutdown()`
- 若后台线程通过键盘事件终止循环，主线程可能尚未退出，因此后台线程需自行调用 `rclpy.shutdown()` 以防止进程挂起

> `rclpy.shutdown()` 是幂等的，多次调用效果等同一次，内部已做线程同步和关闭状态检查。
