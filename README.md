# Sammy

> 住在你桌面上的小家伙。

Sammy 是一个有脸、有声音、有记忆的**个人 AI agent**。它和 Max / Nex 的区别是：Max 和 Nex 是**能力**，Sammy 是**存在感**。

---

## 状态

🟡 **M0 — PRD 阶段**（写代码之前先把 Sammy 是什么想清楚）

## 目录

```
Sammy/
├── README.md          ← 本文件
├── docs/
│   └── PRD.md         ← ⭐ 产品需求文档（唯一事实来源，先改文档再改代码）
├── src/               ← 代码（M1 开始）
└── assets/            ← 表情、图标、音效等资源
```

## 铁律

1. **PRD 是唯一事实来源** —— 想加功能，先改 PRD，再写代码。
2. **每个改动一个 commit** —— 旧项目 7959 行零 git 的教训。
3. **API key 永不硬编码** —— 走环境变量，`.env` 不进仓库。
4. **旧代码在 `/Volumes/Mac mini/Sammy`，只读参考** —— 需要哪个资产就搬哪个进来，不再就地改。

## 相关

- 旧项目（只读）：`/Volumes/Mac mini/Sammy`（7959 行 Python，4 个版本，0 个 git 仓库）
- 硬件方案：树莓派 4B + 5寸 IPS 触控屏 + MG90S×2 + PCA9685，≈¥400
- 协作方：Max（Mac）、Nex（Linux）
