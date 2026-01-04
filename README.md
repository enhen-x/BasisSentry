# 资金费率套利系统

> 针对小资金（100-10000 USDT）的永续合约资金费率自动套利系统

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp config/exchanges.yaml.example config/exchanges.yaml
# 编辑 exchanges.yaml 填入你的 API Key

# 3. 运行扫描器
python scripts/run_scanner.py

# 4. 启动套利
python scripts/run_arbitrage.py
```

## 核心特点

- 🎯 **流动性筛选**: 专注日交易量 $500K-$5M 的中等池子
- ⚡ **自动化执行**: 毫秒级响应资金费率变化
- 🛡️ **风险控制**: Delta 中性 + 多重安全阈值
- 📊 **实时监控**: Telegram 通知 + 详细日志

## 策略原理

```
正费率 > 0.03%:  买入现货 + 开空合约 → 收取资金费
负费率 < -0.03%: 卖出现货 + 开多合约 → 收取资金费
```

## 文档

- [系统架构](docs/architecture.md) - 详细设计文档
- [配置说明](docs/configuration.md) - 参数配置指南
- [API 指南](docs/api_guide.md) - 交易所 API 使用

## 系统要求

- Python 3.10+
- 稳定的网络连接
- 交易所 API Key

## 风险提示

⚠️ **加密货币交易存在风险，请勿投入无法承受损失的资金**

---

*Made with ❤️ for crypto arbitrage*
