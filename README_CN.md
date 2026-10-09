# skill-smith

通过调研、受守卫保护的脚手架和独立证据评审，创建职责清楚的 skill。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Research-first](https://img.shields.io/badge/Design-research--first-green?style=flat)](skills/skill-smith/reference/research-first.md)
[![Acceptance gate](https://img.shields.io/badge/Evidence-independent%20review-green?style=flat)](skills/skill-smith/reference/acceptance-gate.md)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#语言)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.2.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

## ⭐ 先读设计理念

生成一份像样的 SKILL.md，还不能证明它会正确触发或改善任务结果。
skill-smith 在生成之前安排调研，在生成之后要求测量证据。调研明确问题、替代方案和证明案例；
独立评测者在实施前冻结 policy 与保留测试集。最终候选包含完成后的文档和版本信息。

调研、生成、评测和迭代交给已有工具；本工具负责交接、仓库结构和证据契约。
这种设计的代价是：评测能力缺失时，流程会明确停在缺口上。确定性检查不能替代真实测量，
文件 hash 也不能证明一份自述结果确实发生过。

接受候选需要独立评审批准同一份最终候选和证据。设计选择见 [PHILOSOPHY.md](PHILOSOPHY.md)；
文档完成、评审与发版责任见[文档契约](skills/skill-smith/reference/documentation.md)。

## 能做什么

- 为单个或一组新 skill 安排调研、重叠检查和可用生成器。
- 生成版本一致的骨架，固定 Guards / Style 子模块，并安装缺失时会阻断的钩子。
- 按冻结的 policy 与候选核对 G1/G2 分数及必需的 G3-G8 证据。
- 测量整个技能库的预算与重叠情况，保留缺失清单和缺少可见性测量的事实。
- 将已获独立批准的证据交给可用的 self-evolve provider，另行核验授权范围内的安装或发布。

改进已有 skill 用 [self-evolve](https://github.com/DaizeDong/self-evolve)，
寻找现成 skill 用 [market-intel](https://github.com/DaizeDong/market-intel)。
批量创建仍需逐个候选提供证据，并共享同一个技能库预算。

## 创建流程

流程串起已有工具和独立评测者的工作。批量创建时，每个候选都要走完同一套证据和评审流程。

<p align="center">
  <a href="docs/diagrams/workflow-cn.png"><img src="docs/diagrams/workflow-cn.png" alt="技能创建流程：调研、冻结评测策略、实现、证据校验和独立评审，以及迭代和授权交付。" width="760"></a>
</p>

[绘图源文件（DOT）](docs/diagrams/workflow-cn.dot) · [重新生成 PNG](docs/diagrams/render.py)

证据 CLI 只校验已有产物，始终返回 `accepted: false`。所需证据缺失、未通过或含合成样例时，
候选都不能被接受。候选或 policy 一旦改变，就要重新绑定证据，并从头完成两轮独立评审。
候选和 policy 均未变时，补齐证据后重新校验；需要修订时，回到冻结评测策略的步骤。

实际测量由证据 CLI 之外的评测者完成。[迭代交接](skills/skill-smith/reference/iterate-handoff.md)
使用已安装的 provider：程序化结果（A）、带日期的外部锚点（B），或场景、rubric、人工或异构评审证据（C）。
所需能力必须已经实现且确实可用；只有 scenario-eval 设计文档，还不能运行评测。provider 不可用时，缺口必须保留。

## 安装

```text
/plugin install github:DaizeDong/skill-smith
```

源码安装：

```bash
git clone --recurse-submodules https://github.com/DaizeDong/skill-smith.git
cd skill-smith
git config core.hooksPath .githooks
python -m pip install -r requirements.txt
```

两个子模块都要初始化；已有 clone 可运行 `git submodule update --init --recursive`。
参与提交前设置适合公开的身份。已安装别名和资源路径需要另行核验，见[部署说明](skills/skill-smith/reference/deploy.md)。

Python 调用方可以构建并安装 `skill_smith` 技能目录与运行适配包。
可选执行功能使用已安装的 llmcall，要求其 0.3.0 接口，并拒绝所选运行环境无法强制执行的要求。
依赖、wheel 构建、来源路径边界、覆盖状态和验证范围见
[Python API](skills/skill-smith/reference/python-api.md)。

## 快速开始

提出“用 skill-smith 创建一个完成某任务的技能”，或提供一组不同职责。
集中填写[交付 brief](skills/skill-smith/reference/intake-delivery.md)，调研替代方案，
冻结评测 policy / 保留测试集，并由生成负责人完成全部适用文档。

```bash
python skills/skill-smith/scripts/scaffold_skill.py my-skill --description "Create a reusable report from supplied public input." --topics "reporting"
python skills/skill-smith/scripts/check_conformance.py ../my-skill --stage draft
```

草稿检查不代表接受候选。先完成实现、双语 README、设计理念、SKILL、ROADMAP、CHANGELOG
以及适用的配置和参考文档。按每项受影响行为记录文档影响。
最终 snapshot 前运行 accepted 检查，随后收集绑定候选的证据并独立评审：

```bash
python skills/skill-smith/scripts/check_conformance.py ../my-skill
python skills/skill-smith/scripts/acceptance_gate.py --repo ../my-skill --snapshot
python skills/skill-smith/scripts/acceptance_gate.py --repo ../my-skill --manifest PRIVATE_MANIFEST --policy PRIVATE_POLICY --policy-sha256 FROZEN_SHA256
```

证据命令只校验契约，输出 JSON，在独立评审完成前返回非零。
合成证据仍为 `synthetic_only`；非合成的自述证据仍为 `independent_review_required`。
两轮通过的独立评审必须绑定同一候选、policy 和原始结果。
代码、文档、fixture 或元数据变化会使旧 snapshot 与评审连续轮次失效。
评审还要核对双语含义和实际行为，不能只看结构检查。

## 私有运行数据仓

报告、真实 brief、评测日志、裁剪清单和备份保存在已核实为 PRIVATE 的版本化伴生仓。
公开 TOOL 文档只保留可复用理念和生成器制作的合成例子。
主仓的[存储契约](storage.contract.json)规定保留路径和预算；保留当前结构化状态、必要配置、
恢复依赖和用户要求的最终产物。提取有用的独立变更后，再按契约清理已被替代的开发材料。
[存储检查器](skills/skill-smith/reference/storage-contract.md)只报告声明和大小，不删除数据。
删除需要已审查的计划，并再次核验 PRIVATE、路径边界和写入已停止的依据。

在工具仓根目录执行，把 OWNER 换成私有伴生仓所属账号：

```bash
gh repo create OWNER/skill-smith-config --private
gh repo clone OWNER/skill-smith-config ../skill-smith-config
printf 'skill-smith\n' > ../skill-smith-config/.companion
mkdir -p ../skill-smith-config/data
touch ../skill-smith-config/data/.gitkeep
git -C ../skill-smith-config add .companion data/.gitkeep
git -C ../skill-smith-config commit -m "Initialize private companion"
git -C ../skill-smith-config push -u origin HEAD
gh repo view OWNER/skill-smith-config --json visibility --jq .visibility
export SKILL_SMITH_CONFIG="$(cd ../skill-smith-config && pwd)"
```

已有伴生仓时 clone 并设置同一变量。可见性查询必须返回 `PRIVATE`。
写入前刷新可信可见性回执；上述查询不会刷新回执。
选择优先级、准确输出路径、写入准入、仅控制台运行和恢复步骤见
[运行数据发现与输出](skills/skill-smith/reference/storage-contract.md#runtime-discovery-and-outputs)，
传输证明见 [Guards 伴生仓核验](guards/COMPANION.md#verifying-a-companion)。
Smith 仅管理运行数据；存储参考文档中的外部配置输入由 Profile Sync 和操作者初始化。
G8 合规本身不证明存储已就绪。

## 技能库与 Fleet 检查

预算和去重共用用户技能及活动插件清单。可同时用 `--skills-dir`、
`--installed-plugins` 指定另一套清单。缺失、不可读或冲突条目保留为 `UNKNOWN`
并计入 unresolved；插件缓存里的旧版本不算活动技能。
预算需要当前捕获的 `--listing FILE` 才能证明可见性。
历史容量仅供参考，`--capacity N` 表示当前策略。实测丢失与预计移除分别记录；
需要用户决定移除时保留 BLOCKED，不完整观测不能给出 G3 PASS。

`fleet_check.py` 只读检查别名、本地 conformance、预算、DATA 边界、远端 guard workflow
和默认分支的每个 workflow。`--offline` 将远端项目标为未观测。
引用带覆盖率的 VERDICT，不要只引用失败数。
CI 说明会区分已执行的 job 和零步骤 / 无 runner 的失败，不能据此猜测原因。

本地 conformance 保留安全与包格式检查，将文档结构交给
`style/tools/doc_contract.py --root . --profile skill --stage accepted`；检查器缺失会失败。
SKILL 超过 12,000 字符警告，超过 16,000 字符失败；已有的限期缩减例外会明确显示。
必需相对资源路径必须存在。这些检查不证明真实效果、远端 CI 或文档语义准确。

## 版本与维护

plugin manifest 是版本来源；双语 README 徽章、ROADMAP Current 和最新数字版 CHANGELOG
保持一致。后续重要变化先写 Unreleased，保留旧历史。
规则只在[文档契约](skills/skill-smith/reference/documentation.md)维护。

```bash
python skills/skill-smith/scripts/bump_version.py . --level patch --dry-run
```

发布前检查和历史保留遵循文档契约；版本选项见
[脚手架参考](skills/skill-smith/reference/scaffold.md#bump-version-preparation)。
工具同步五处版本，不提交、不打 tag、不推送。Python 包发版还需按 Python API 文档同步
`pyproject.toml` 版本；准备完成不代表已经发布。

## 证据与运行前提

需要 Python 3.10+、Git 和 `requirements.txt` 中的 PyYAML。
模型和 agent 工作使用 已安装的 `llmcall` 当前路由、超时与回退策略。
先核对所选调研、生成器和评测能力；缺失时明确保留缺口。

离线测试需要 `requirements-dev.txt` 和 PATH 中的 POSIX `sh`。
Windows 可使用 Git Bash，或在当前 shell 加入 Git for Windows 的 `bin`：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -c pytest.ini tests/ tools/ -q -ra
```

测试从当前检出的 kit 版本建立本地镜像，禁止网络 Git 协议。
生成的 fixture 只能验证契约，不能证明真实任务改进或外部集成。

## 局限

G8 读取源仓声明的适用性和原生生命周期入口。
静态检查保留“就绪状态未测”；只有 `--run-synthetic` 才执行已审查的合成夹具命令，
分别记录空模板必填项拒绝、模板确定性和已配置 A/B 检查结果。
scenario-eval 和外部 provider 必须实际存在才能选择。
同账号私有路径只提供流程隔离，不能证明无法读取。
安装、发布、外部就绪和实际结果都需要分别观测。

## 语言

English（`README.md`）· 中文（`README_CN.md`）。两份描述同一套当前契约。

## Roadmap · 许可

见 [ROADMAP.md](ROADMAP.md) · [LICENSE](LICENSE)（MIT）。
