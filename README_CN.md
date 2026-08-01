# skill-smith

创建 Claude Code skill,单个或一整套,并达到业界领先、经测试真实可用的标准：先调研全行业，再按规范脚手架，最后对任何过不了验收闸的产物一律拒绝上线。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![理念先行](https://img.shields.io/badge/%E8%AE%BE%E8%AE%A1-%E8%B0%83%E7%A0%94%E5%85%88%E8%A1%8C-green?style=flat)](skills/skill-smith/reference/research-first.md)
[![验收闸](https://img.shields.io/badge/%E4%B8%8A%E7%BA%BF-%E8%BF%87%E9%97%B8%E6%89%8D%E7%AE%97-green?style=flat)](skills/skill-smith/reference/acceptance-gate.md)
[![语言](https://img.shields.io/badge/%E8%AF%AD%E8%A8%80-EN%20%2F%20CN-blue?style=flat)](#语言)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.3-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ 先读这里, 设计理念

skill-smith 立足一条原则：**skill 不是"生成出来"就算完成，而是"被证明可用"才算完成。** 由此推出两点，贯穿整个仓库的每个决策：

1. **先调研，再设计（P1）。** 靠猜做不出"业界领先"。在写新 skill 的第一行之前，skill-smith 先把一次广泛调研委托给 [`market-intel`](https://github.com/DaizeDong/market-intel),业界最佳参考实现、可借鉴的前沿设计、需规避的 anti-patterns。设计目标是**调研出来的当下最高水准**，不是嘴上声称的。
2. **生成 ≠ 可用（P2）。** 社区到处在量产"看着没问题、却静默失效"的自动生成 skill（约 50% 根本不触发；实测审计显示多数低于可用质量线）。所以 skill-smith 对"被接纳"的态度，与 [`self-evolve`](https://github.com/DaizeDong/self-evolve) 对"真改进"的态度完全一致：只有过了反自欺**验收闸**（相对 baseline 的可测 eval 提升 + held-out 触发率 + token 预算 + 去重 + 安全 + 规范一致 + 单一职责聚焦）才算数。

因此 skill-smith **不**做又一个更大的生成器。它是一个**薄编排层**，只 own 别人不 own 的那道缝，把重活委托给你已经在跑的工具。

📜 **[完整设计理念 -> PHILOSOPHY.md](PHILOSOPHY.md)**（6 条原则，每条都给"打补丁 vs 改根因"对照和它产生的真实决策）。

---

## 它是什么（不是什么）

零件你都有了：`market-intel`（调研编排）、`self-evolve`（反自欺自迭代）、Skill Repo Spec v1（输出规范）。缺的是把它们**缝合成"把一个新 skill 做好"**的那一层。这就是 skill-smith。

它只做别人不做的，其余全部委托：

1. **调研先行**, 把"业界标杆 + 前沿设计"调研委托给 `market-intel`（前端引擎）。
2. **规范脚手架**, 确定性吐出符合 Skill Repo Spec v1 的仓库骨架（必备 7 文件、徽章、版本四源同步、plugin 指纹）。
3. **验收闸**, eval 提升、触发率、系统提示 token 预算、跨库去重、安全审计、规范一致、聚焦度。不过 = 显式拒绝，绝不静默上线。
4. **自迭代交棒**, 把已接纳的 skill 交给 `self-evolve`（后端引擎）做回归门控的迭代优化。
5. **批量**, 扇出一**系列**候选 skill，逐个过闸，统一受一个全局"库预算管家"约束。

它**不是**：从零生成器（它调用 Skill_Seekers / 官方 skill-creator）、eval 框架（它调用 agent-skills-eval / scenario-eval）、迭代引擎（它调用 self-evolve）。它是**缝 + 闸**。

它**不用于**：改进**已有** skill（那是 `self-evolve`），或回答"有没有现成的 X skill"（那是 `market-intel` 的 `ready-skills` 域）。

## 安装

```
/plugin install github:DaizeDong/skill-smith
```

或手动克隆：

```bash
git clone https://github.com/DaizeDong/skill-smith.git ~/.claude/plugins/skill-smith
```

（维护者部署：源在 `CodesClaude/skill-smith`，用 PowerShell junction 部署到 `~/.claude/skills/skill-smith`,见 [`reference/deploy.md`](skills/skill-smith/reference/deploy.md)。）

## 快速开始

> "用 skill-smith 创建一个能 <做 X> 的 skill。"（单个）
> "用 skill-smith 批量创建 <A、B、C> 这几个 skill。"（一套）

skill-smith 会：market-intel 调研全行业 -> dedup 查你现有库 -> 脚手架规范仓库 -> 起草并优化触发描述 -> 跑验收闸 -> 交给 self-evolve -> 部署。

也可直接跑脚本：

```bash
python skills/skill-smith/scripts/scaffold_skill.py my-skill \
  --tagline "一行,动词开头,量化收益。" \
  --description "何时触发 + 做什么 + 覆盖范围,一段写完。" \
  --topics "domain-a,domain-b"

python skills/skill-smith/scripts/check_conformance.py ~/CodesClaude/my-skill   # Spec v1 检查器
python skills/skill-smith/scripts/bump_version.py ~/CodesClaude/my-skill --level patch  # 五处版本
python skills/skill-smith/scripts/budget_check.py                            # 库的系统提示词预算
python skills/skill-smith/scripts/dedup_check.py                             # 描述重叠
python skills/skill-smith/scripts/fleet_check.py                             # 全 fleet 体检, 只读
```

`check_conformance.py` 还会量 SKILL.md 自身, 因为这个文件在该 skill **每一次**被调用时都要付费:
**超过 12,000 字符告警, 超过 16,000 字符判失败**; 它写下的每个相对路径都必须在盘上解析得到;
指令文本要直接写规则, 而不是写"第几轮加了什么"。2026-07-31 当天已经超线的文件按名字连同实测大小
进白名单, 只许变小不许变大, 所以那份名单只会越来越短。每条白名单还带一个**有日期的缩减目标**:
它每一轮都要大声 WARN 并把算式写出来, 每个仓的汇总行会写明 `N grandfathered, M chars over target`,
一旦过了目标日期还没降到目标以下就直接判 FAIL。白名单当初正好就是那五个超线文件, 所以如果不这样,
这道闸第一次跑全 fleet 就是零条 FAIL, 而那覆盖着 17% 的文件和 40% 的常驻字符,
一次没有失败的运行读起来就等于"全 fleet 在预算内"。

`budget_check.py` 回答的是唯一一个"失败本身就看不见"的问题: 超过预算后 loader 会静默丢掉 skill 描述,
于是那个 skill 依然存在, 只是永远不再触发。它分三层分别报数(`ours`、`local` 用户 skill、`plugin` skill),
plugin 那层从 `installed_plugins.json` 读而不是 glob 缓存目录(缓存里每个 plugin 存着 2 到 4 个旧版本),
同时打印文档写的 15,000 字符预算, 和 2026-08-01 用一份真实 skill 清单逐条对拍磁盘上每个 `SKILL.md`
**实测**出来的容量: 163 个有文件的 skill 里 79 个保住了描述, 84 个只剩一个光名字, 活下来的行合计 21,565 字符,
而整个库声明了 53,821 字符。

这次实测推翻了这个工具原先的三条断言。截断**不是**按加载顺序砍掉连续的尾巴, 所以它不再猜受害者名单:
不给 `--listing FILE` 时只报"至少多少个 skill 必须丢描述"的**下界**, 并明说名字无法从磁盘推出来;
给了就**实测**出来。损失也不局限在用户层, 绝大部分落在 plugin 层。卸载 plugin 更不是没用, 它是最大的那根杠杆。

判定颜色跟的是**杠杆**, 不是严重程度。今晚动手改文字就能关掉的(我们自己的描述超过 180 字符上限,
或者超额小到把描述裁到上限就能覆盖)判 **FAIL** 红灯, 并点名具体裁哪几条。改文字怎么都吸收不掉的超额判
**BLOCKED** 黄灯: 每次运行都完整陈述, 带两边的算术, 外加一份按字符成本排序、标好价钱的 plugin 卸载清单。
因为"卸个东西吧"不带数字只是耸肩, 不是杠杆。黄不是淡一点的红, 它的意思是剩下的只能是"决定不要什么",
而一个永远不变的颜色就等于没人再看。只有每个 skill 描述的**字数上限**仍然只对我们这层判失败,
因为那是本仓产出 skill 的 Spec-v1 写作规则, 不是对早于该规范的 skill 的评判。完整排名跑 `--plugins`。

`fleet_check.py` 是上面那个检查器一直缺的 driver。它把 `check_conformance.py` 铺到每个 plugin 仓上,
再补上没人查的五件事: skill junction 能否解析、标为 PUBLIC 的仓**在远端默认分支上**是否带齐每个 guard
workflow(`pii-guard` **和** `dash-guard`)、已安装的库是否还塞得进系统提示词、解析出的真实运行数据目录
是否落在某个 **PUBLIC 或可见性未知**的仓里(落在私有伴生仓里是**正确形态**, 该行 PASS 并写明是哪个仓)、
以及**我们自己每个仓的每个 workflow**(公开私有都算)**在远端默认分支上**到底绿没绿(每个仓每个
workflow 各出一行)。
它**只读, 没有 `--fix`**, 也从不 `git fetch`, 任一项 FAIL 即非零退出, 并写一份带 UTC 时间戳的状态 JSON,
让定时调用方能把"这轮真跑了"和"这轮通过了"分开判断。加 `--offline` 可跳过需要联网的探针。

到 2026-07-31 为止, 上面有两条答案其实一直在答另一个问题。CI 那项问的是**任意 ref** 上最新的一次运行,
于是往话题分支推一次绿, 就被当成默认分支的状态打出来; 2026-07-22 那天, 某个仓的 `pii-guard` 会因为话题
分支上一次绿的运行而显示 PASS, 而它自己 `master` 上最新那次是 FAILURE。现在它按默认分支过滤, 而
"默认分支上没有任何运行"记为 `UNKNOWN`, 不再悄悄拿别的 ref 顶上。数据边界那项背后的可见性判断, 过去是
**先读**缓存的可见性表、只有查不到才问 `gh`, 于是一行过期的 JSON 就能把一个躺在公开仓里的数据目录永远
放行, 而这台机器上根本没有任何东西会去刷新那份文件。现在改成先问 `gh`, 只有 `gh` 答不上来时缓存才有投
票权, 而且只在信任窗口内有效: 一份永不过期的缓存不是缓存, 是断言。

workflow 这一项查的是**远端**而不是本地工作树, 这是刻意的: 以前它 stat 本地 clone, 于是一个已经 commit
但从未 push 的 guard workflow, 会让一个远端根本没有任何 guard 的 PUBLIC 仓判成 PASS。现在 `UNKNOWN`
只有一个含义: "这轮没能观测到答案"(没有 `gh`、未认证、被限流、离线), 所以它不影响退出码才是安全的;
而一个真的回答了的远端给出的否定答案是 `FAIL`。没观测到的行会单独打在 `UNOBSERVED` 标题下并写进状态
JSON, 因为"没人看得了的 fleet"绝不能读起来像"干净的 fleet"。

每轮结束会打出一行 **VERDICT**, 上面带着覆盖率, 调用方应当原样引用这一行, 而不是拿计数自己拼形容词。
2026-07-30 那晚, 夜间简报把 "pass 86, fail 0, skip 82" 说成了"全绿", 而第二天审计翻出的每一条缺陷
当时就已经在 fleet 里了: 近一半被检面根本没评估, 报告却读起来像干净的。现在 `GREEN` 只能表示
"评估过的都没失败", `AMBER` 表示有今天无法用一次修改消掉的发现, 而同一行会写明到底看了多少。

覆盖率子句紧跟在 verdict 那个词后面, 而不是排在行尾; 抽样不完整时它会喊出来:
`VERDICT GREEN OVER 56% OF ROWS (112 of 200; 88 NOT EVALUATED)`。只是"把比例写在这一行上"并不够:
它原本排在 verdict 右边第四个字段, 而那一轮 200 行里有 88 行根本没被评估, 于是扫到 `VERDICT` 后面
第一个词的读者看见 `GREEN` 就停了。这还是当年那句"全绿", 只不过把更正印在了没人读到的地方。`TOTAL`
行的计数下面也带同一句。状态 JSON 里那个给机器读的 `verdict` 字段仍然只是那个裸词。

这份报告现在是并发的。所有远端问题跑在线程池上, 每个不同的 slug 只问一次并缓存, 于是整轮从 128s
降到约 28s。对一份要人手动跑的报告来说, 墙钟时间就是正确性的一部分: 两分钟的报告会被中途放弃, 而这
和"没人跑的闸门"是同一个下场。加速不是靠少问换来的, 并且这条规则由测试守住: 行集合、每个分节的计数、
以及整个报告正文, 都和串行版本逐字节相同, 干净场景和失败场景都一样。

`bump_version.py` 一次改齐五处版本(plugin.json、两个 README 徽章、ROADMAP、CHANGELOG)。仓库已经
版本不一致时它直接拒跑而不是把不一致掩盖掉;它也从不 commit / push,发版是人的决定。

## 如何触发

触发词：*创建 skill、做一个 skill、脚手架 skill、写新 skill、批量创建 skill、做一套 skill、优化 skill 的触发/描述、skill 工厂。*

## 局限

- v0.1 交付**框架**：调研先行工作流 + 确定性脚手架 + Spec-v1 检查器 + 预算/去重检查。验收闸的 eval-lift 接线（agent-skills-eval / scenario-eval）与 self-evolve 交棒在 v0.2/v0.3（见 [ROADMAP.md](ROADMAP.md)）。
- 假定已装 `market-intel` 与 `self-evolve`；没有时降级为普通 web 调研 + 手动闸，并会**显式说明**（绝不静默）。
- 它优化的是**正确、聚焦、被证明**的 skill，不是数量,按设计，它会拒绝加入会撑爆库 token 预算的 skill。

## 语言

中文（`README_CN.md`）· English（`README.md`，权威版）

## Roadmap · 贡献 · 许可

见 [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE)（MIT）。
