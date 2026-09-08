# RE-50 实例分析

状态：初稿。本文用于解释实验过程和错误机制，不修改原始标签、结果表或模型原始响应。

## 1. 分析口径

选择 5 个代表性实例：

| 实例 | 复杂度 | 原始标签 | 选择原因 |
|---|---:|---:|---|
| `17266` | `>300` | 1 | 长源码；M1/M3 正确，M2 错误 |
| `1912` | `>300` | 1 | 长源码；M1 正确，M2/M3 错误 |
| `489` | `100–300` | 1 | 三种方法均正确 |
| `18224` | `100–300` | 1 | 三种方法均判负，观察共同失败和标签边界 |
| `19269` | `100–300` | 0 | M1 误报，M2/M3 判负 |

每个实例按同一顺序分析：

```text
源码和原始标签
  -> 人工标注外部调用、状态读写、保护条件
  -> M1 直接阅读
  -> M2 固定 balance/call 定位
  -> M3 LLM 生成关键词定位
  -> 比较候选窗口、证据行和最终标签
  -> 判断错误发生在定位、上下文还是语义判断
```

人工复核结论只作解释，不替代数据集标签。正式复核应先盲看源码和 RE 定义，再查看模型输出。

## 2. 实例一：contract 17266

源码：[01_sources/17266.sol](01_sources/17266.sol)；逐样本结果见 [experiment_results.csv](02_results/experiment_results.csv)；原始响应见 [raw_results.jsonl](03_raw_evidence/raw_results.jsonl)。

### 2.1 关键源码逻辑

```solidity
341  function submitPool (uint amountInWei) public onlyOwner noReentrancy {
342    require (contractStage == 1);
347    finalBalance = this.balance;
348    require (receiverAddress.call.value(amountInWei).gas(msg.gas.sub(5000))());
349    if (this.balance > 0) ethRefundAmount.push(this.balance);
350    contractStage = 2;
```

逻辑链：`call` 发生在 `contractStage = 2` 之前；但函数带有 `noReentrancy`，保护条件必须纳入判断。

### 2.2 三种方法

| 方法 | 候选/输入 | 预测 | 模型证据 | 过程判断 |
|---|---:|---:|---|---|
| M1 直接阅读 | 全部 382 行 | 1 | `[196]` | 标签正确，但证据行未指向 `submitPool` 的调用顺序 |
| M2 固定关键词 | 68 行 | 0 | `[201,347]` | 看到了保护和提款逻辑，未形成 `348 -> 350` 链 |
| M3 LLM 关键词 | 89 行；`balance, withdraw, _ethDeposit, noReentrancy, locked, transfer` | 1 | `[347,350]` | 捕获了状态更新，但理由忽略 `noReentrancy` 的有效性 |

### 2.3 初步复核

该例不是简单的关键词未命中：M2/M3 都命中了相关区域。主要分歧是“外部调用前状态未更新”与“重入保护是否阻断回调”的优先级。初步标记：**条件性风险，保护条件需人工确认**。

## 3. 实例二：contract 1912

源码：[01_sources/1912.sol](01_sources/1912.sol)。

### 3.1 关键源码逻辑

```solidity
1835  function buy(uint256 _tokenId) external payable {
1836      require(internalNFTInfo[_tokenId].sell, "Item is not available for sale!");
1838      address currentOwner = ownerOf(_tokenId);
1845      payable(currentOwner).transfer(internalNFTInfo[_tokenId].price);
1852      purchaseToken.safeTransferFrom(msg.sender, currentOwner, internalNFTInfo[_tokenId].price);
1859      handleTokenTransferOnBuy(_tokenId);
```

逻辑链：`buy` 先向 `currentOwner` 或代币合约交互，最后才调用 `handleTokenTransferOnBuy` 更新出售状态。漏洞是否可利用，还取决于接收方是否为可回调合约及状态更新函数的具体内容。

### 3.2 三种方法

| 方法 | 候选/输入 | 预测 | 模型证据 | 过程判断 |
|---|---:|---:|---|---|
| M1 直接阅读 | 全部 1962 行 | 1 | `[345,360]` | 标签正确，但证据行是接口区域，证据定位失败 |
| M2 固定关键词 | 119 行 | 0 | 空 | 候选主要由 ERC721 接口和库代码组成，业务路径被稀释 |
| M3 LLM 关键词 | 158 行；`balance, _balances, ownerOf, _owners, safeTransferFrom, functionCall, transfer` | 0 | 空 | 关键词覆盖标准库概念，未保留 `buy` 的完整顺序 |

### 3.3 初步复核

这是典型的长源码上下文压缩案例。M3 不是没有命中关键词，而是候选过宽，标准库代码占据注意力，导致 `1845/1852 -> 1859` 的业务顺序没有成为判断中心。初步标记：**正例条件性支持；M3 主要失败在上下文组织**。

## 4. 实例三：contract 489

源码：[01_sources/489.sol](01_sources/489.sol)。

### 4.1 关键源码逻辑

```solidity
79  function deposit() payable public {
80      participants.push(Participant(msg.sender, (msg.value * multiplier) / 100));
81      payout();
84  function payout() public {
85      uint balance = address(this).balance;
93          participants[payoutOrder].payout -= payoutToSend;
95          if(!participants[payoutOrder].etherAddress.send(payoutToSend)){
96              participants[payoutOrder].etherAddress.call.value(payoutToSend).gas(1000000)();
```

逻辑链：`deposit -> payout -> send/call`；候选窗口同时包含余额、参与者状态和外部交互。

### 4.2 三种方法

| 方法 | 候选/输入 | 预测 | 模型证据 | 过程判断 |
|---|---:|---:|---:|---|
| M1 直接阅读 | 全部 122 行 | 1 | `[38,40]` | 标签正确，但证据行与漏洞路径不一致 |
| M2 固定关键词 | 10 行 | 1 | `[85,96]` | 命中余额读取和外部调用，窗口较集中 |
| M3 LLM 关键词 | 23 行；`balance, participants, payoutOrder, withdraw, weak_hands` | 1 | `[96,97]` | 命中外部调用，最终判断正确 |

### 4.3 初步复核

短中等源码中，固定关键词已能形成较紧凑的候选窗口，LLM 关键词进一步补充了参与者和支付顺序概念。该例说明关键词策略在结构简单、关键路径集中时可以工作。初步标记：**支持正例，定位和判断均较稳定**。

## 5. 实例四：contract 18224

源码：[01_sources/18224.sol](01_sources/18224.sol)。

### 5.1 关键源码逻辑

```solidity
109  function bid() public payable {
110      require(msg.sender == tx.origin, "no contracts");
113      // Give back the last bidders money
120          winning.transfer(lastBid);
133      lastBid = msg.value;
134      winning = msg.sender;
138  function end() public {
143      IERC1155(tokenAddress).safeTransferFrom(address(this), winning, tokenId, 1, new bytes(0x0));
149      ended = true;
```

逻辑链：`bid` 中存在外部转账但有 `tx.origin` 限制；`end` 中存在外部调用且 `ended` 在调用后更新。是否形成可利用重入链，需要确认调用目标和可再次进入的路径。

### 5.2 三种方法

| 方法 | 候选/输入 | 预测 | 模型证据 | 过程判断 |
|---|---:|---:|---:|---|
| M1 直接阅读 | 全部 174 行 | 0 | 空 | 注意到 `tx.origin`，判定回调入口受限 |
| M2 固定关键词 | 10 行 | 0 | 空 | 候选覆盖 `transfer` 和 `end`，未判为漏洞 |
| M3 LLM 关键词 | 17 行；`balance, transfer, call` | 0 | 空 | 候选覆盖外部交互，但没有建立可重入路径 |

### 5.3 初步复核

三种方法结论一致，但原始标签为 1。该例应作为标签边界案例：外部调用存在，不等于 RE 成立；必须继续确认攻击者是否能控制被调用方、重新进入哪个函数以及状态是否可被重复利用。初步标记：**证据不足，不能据此修改原始标签**。

## 6. 实例五：contract 19269

源码：[01_sources/19269.sol](01_sources/19269.sol)。

### 6.1 关键源码逻辑

```solidity
82  function signHash(uint256 _hash) public onlyAssociatedSigner {
83      address[] memory signatures = _hashToSignatures[_hash];
85      bool alreadySigned = false;
92      if (alreadySigned == true) {
96      _hashToSignatures[_hash].push(msg.sender);
```

逻辑链：函数读取签名数组并在最后追加签名，但片段中没有对外部合约的调用。

### 6.2 三种方法

| 方法 | 候选/输入 | 预测 | 模型证据 | 过程判断 |
|---|---:|---:|---:|---|
| M1 直接阅读 | 全部 106 行 | 1 | `[43,51]` | 误报；证据行是合约声明和 modifier |
| M2 固定关键词 | 1 行 | 0 | 空 | 几乎没有候选业务代码 |
| M3 LLM 关键词 | 12 行；`_signerToAgency, msg.sender` | 0 | 空 | 命中状态变量，但没有外部交互 |

### 6.3 初步复核

按本实验 RE 定义，`signHash` 的状态读写本身不能构成重入；需要外部可重入交互。M1 的理由把“外部可调用函数”误当成“外部合约调用”，属于概念性误报。初步标记：**不支持正类，原始标签保留用于指标复现**。

## 7. 跨实例比较

| 观察维度 | 实例证据 | 初步解释 |
|---|---|---|
| 长源码退化 | `1912`：M3 候选 158 行；`17266`：89 行 | 标准库和重复 API 使业务调用顺序不突出 |
| 关键词命中不等于语义命中 | `1912`、`17266` | 关键词覆盖相关词，但未必保留完整调用链和保护条件 |
| 直接方法证据质量 | `489`、`1912`、`19269` 的 M1 证据行均不可靠 | 标签正确不等于证据行正确，需单独审计 evidence_lines |
| 固定规则作用 | `489` 命中集中；`1912` 候选过宽 | 固定关键词适合做可重复基线，不适合代表完整漏洞语义 |
| 标签边界 | `18224`、`17266`、`19269` | 外部调用、状态延后更新、保护条件必须联合判断 |

## 8. 对总体结果的解释

本批次不能简单总结为“LLM 关键词方法和直接阅读效果相同”。更准确的结论是：

1. 总体 F1 差异有限，但 LLM keyword Recall 明显较低，表现为更少误报和更多漏报。
2. 差异集中在长源码；候选窗口变宽后，标准库和非关键调用稀释了业务语义。
3. 关键词策略的失败至少有两类：候选定位不完整、候选虽命中但调用顺序或保护条件判断错误。
4. 模型输出的标签和 evidence_lines 必须分开评价；多个实例出现“标签正确、证据行错误”。
5. 原始标签与源码语义不一致时，应保留原始标签，另记录人工复核结论。

## 9. 下一步

1. 对 25 个正样本盲标 RE 见证行：外部调用、状态读取、状态更新、保护条件。
2. 将 M2/M3 候选窗口与见证行做交集，计算定位 Recall 和空候选率。
3. 为每个实例补充一条最终错误归因：`定位遗漏`、`上下文稀释`、`顺序误判`、`保护条件误判` 或 `标签边界`。
4. 人工复核完成前，不修改 `experiment_results.csv` 中的原始标签和模型结果。
