# 四个拓展任务的可解释性方法

## L1 · 一个模型单元能预测一个人类神经元的语义偏好吗？

Jamali 等记录了听句子时单个神经元对词的放电，同时公开了词汇及其语义分组。这里事先固定人类细胞 1，在九组词中分别求平均放电率，得到一条九点调谐曲线。模型读取固定载句中探测词的最后一个 token。两侧可比较的是九个语义域的响应结构，人听到的上下文与模型载句不同。[Jamali 等的单细胞研究](https://www.nature.com/articles/s41586-024-07643-2) · [原始放电与词汇数据](https://figshare.com/articles/dataset/Semantic_encoding_during_language_comprehension_at_single_cell_resolution/26046127)

Bills 等用高低激活样例形成解释，再检验解释对未见数据的预测力。任务采用其中的样例检查和事前预测，向 Agent 展示每个候选单元的高低激活词及开发曲线。冻结一个单元后，分别用未见词和独立人类试次重算两侧曲线，以九点 Pearson 相关评分，并列同层 32 个随机单元的平均相关。[Bills 等的激活解释与检验](https://openaipublic.blob.core.windows.net/neuron-explainer/paper/index.html)

## L3 · 哪条模型内的连接影响了输出？

Wang 等在 GPT-2 的间接宾语任务中干预特定信息传递路径，Goldowsky-Dill 等给出了路径替换（path patching）的形式化定义。本任务从原句提取一个注意力头的输出贡献，加到乱序句指定接收端的残差输入上。仅让接收端八个 MLP 单元因此产生的输出变化继续传播，在目标词出现前测量其 log 概率。计算每条路径相对同层其余 11 个头的额外恢复量。测试还将八个接收单元的输出权重置零，确认指定路径的效应随之消失。因果结论的对象是 distilgpt2 内的这条连接。[Wang 等的电路实验](https://arxiv.org/abs/2211.00593) · [Goldowsky-Dill 等的路径替换](https://arxiv.org/abs/2304.05969)

## L4 · 模型能否重现多个语言区一起变化的方式？

Rissman 等分别估计每个试次的响应幅度（beta），在同一条件内按试次配对，计算不同脑区 beta 序列的相关。这里复用 Tuckute 等的逐句估计，保留五个左侧语言区。每一条件内先去掉每位参与者各次扫描的均值，再计算十条区域对相关。模型侧用独立基线句定位五组单元，在相同的句子、分组和区域对顺序下重复计算。最终比较增强相对抑制的十个边变化值，并打乱模型单元组和脑区的对应关系作对照。[Rissman 等的 beta 序列方法](https://doi.org/10.1016/j.neuroimage.2004.06.035) · [Tuckute 等的实验与单试次估计](https://pmc.ncbi.nlm.nih.gov/articles/PMC10120732/)

原研究为增强、抑制两种条件分别选句。条件内的十条边描述区域对不同句子的共同响应，可能包含共同刺激驱动和共同测量噪声。按参与者汇总得到的结构相似性具有区域和条件分辨率。有向生理作用需要额外的干预证据。[Tuckute 等的刺激选择和实验设计](https://pubmed.ncbi.nlm.nih.gov/38172630/)

## L5 · 全脑网络的重组能否预测回避意愿？

Lee 等用动态功能连接研究持续性疼痛。作者的 Study 3 有 48 位参与者，每次扫描取五个时间窗。279 个区域形成 38,781 条无向边，区域归入七个皮层网络、皮层下以及脑干与小脑共九组。参与者在辣椒素（CAPS）和对照（REST）条件下连续报告今后多想避开这种体验。任务保留同一人的五个时间窗，用训练参与者拟合岭回归，在新参与者上检验模型能否预测 CAPS 相对 REST 的回避评分差。[Lee 等的研究及评分定义](https://cocoanlab.github.io/pdfs/LeeJJ2021.pdf) · [作者公开数据](https://figshare.com/articles/dataset/data_zip/13082519) · [仓库现有数据版本](../../mri/tops-fmri/data.lock)

Chan 等用网络内均值 `W` 和网络间均值 `B` 定义系统分离度 `(W − B) / W`。本任务将负边置零，对保留的相关作 Fisher z 变换，去掉区域自身的连接。九个系统的内部边和跨系统边形成 45 个均值。计算分离度时，每个系统的 `B` 对其余八个系统等权。另一个候选将九系统图逐行归一化，读取在图上走两步后回到各自起点的概率。全脑均值和全部 45 个连接块提供两个参照。打乱区域所属的系统后，以同一拟合读出重新预测，可检查结果对系统边界的依赖。模型的输入来自实测人脑连接。[Chan 等的系统分离度定义](https://pmc.ncbi.nlm.nih.gov/articles/PMC4246293/) · [ToPS 作者的示例计算](https://raw.githubusercontent.com/cocoanlab/tops/master/scripts/example_participant_script.m)
