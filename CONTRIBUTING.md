# 贡献指南

感谢你愿意为 **剪贴板管理器** 贡献代码！在提交前请阅读以下规范。

## 开发环境

- Python 3.10 及以上
- Windows 系统（本项目面向 Windows 平台）
- 依赖安装：

```bash
pip install -r requirements.txt
```

## 本地调试

```bash
python clipboard_manager.py
```

> 界面为 Tkinter 实现，主程序集中在 `clipboard_manager.py` 单文件中。

## 提交规范

- **Commit Message** 使用中文或英文均可，建议遵循以下前缀：
  - `feat:` 新功能
  - `fix:` Bug 修复
  - `refactor:` 重构
  - `docs:` 文档
  - `style:` 样式 / 格式
  - `perf:` 性能优化
  - `test:` 测试
- 例如：`fix: 修复悬停图标导致点击卡死的问题`

## 分支规范

- 主分支为 `main`
- 新功能从 `main` 切出 `feature/xxx` 分支
- 修复从 `main` 切出 `fix/xxx` 分支

## 提交 PR 流程

1. Fork 本仓库并克隆到本地
2. 创建功能分支 `git checkout -b feature/xxx`
3. 完成开发并验证运行正常
4. 提交并推送：`git push origin feature/xxx`
5. 在 GitHub 上发起 Pull Request，说明改动内容与动机

## 开发注意事项

- 界面所有像素尺寸请通过 `S()` 缩放函数适配高 DPI
- 画布上的可点击元素，其悬停/离开事件中**不要重建元素**（会导致 Tk 事件派发卡死），请使用 `itemconfigure` 修改样式
- 提交前请确保程序可正常启动、打包命令可执行

## 问题反馈

使用中遇到 Bug 或有功能建议，欢迎提交 [Issue](https://github.com/ciyuana71/clipboard-manager/issues)。
