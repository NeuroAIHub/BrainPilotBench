# Brain-Score 离线实现核查

2026-11-11，核查九个首批 benchmark ID。固定来源为 Vision `c5608668783fe654f83611305fb7e717db0a0cbf`、Language `cc9f623151b5e64be1919c8a8a8b08edc317b784`。本次仅获取软件源码，没有下载刺激、神经数据、ceiling文件或模型权重，没有把合成输入作为真实评测成绩。源码核查副本保存在 `/tmp/bpb-bs-source-audit-20261111/{vision,language}/`。

结论：九个任务可以通过“本地输入注入 + 保留上游评分流程”的方式离线实现。Vision可直接实例化通用 `NeuralBenchmark`；Language需用轻量子类替换有下载副作用的构造器，继承官方 `__call__`。最容易改变协议的地方是分组切分、聚合顺序、Futrell的绝对值相关、上下文重置，以及默认层选择造成的测试数据复用。

## 九个 ID 的执行契约

| registry ID | 实际 benchmark.identifier / version | 数据准备 | 预测/评分协议 |
| --- | --- | --- | --- |
| `MajajHong2015public.V4-pls` | `MajajHong2015.V4.public-pls` / 4 | `MajajHong2015.public`；squeeze单个time_bin，选V4，transpose presentation×neuroid；沿非repetition的presentation元数据分组平均 | 8°、50 trials；PLS25；object_name分层随机10次90/10 |
| `MajajHong2015public.IT-pls` | `MajajHong2015.IT.public-pls` / 4 | 同上，选IT | 同上 |
| `FreemanZiemba2013public.V1-pls` | `FreemanZiemba2013.V1.public-pls` / 1 | `FreemanZiemba2013.public`；选V1；保留neuroid索引；选50–200 ms的一毫秒time_bin，时间平均，再沿重复平均 | 4°、20 trials；PLS25；texture_type分层随机10次90/10 |
| `FreemanZiemba2013public.V2-pls` | `FreemanZiemba2013.V2.public-pls` / 1 | 同上，选V2 | 同上 |
| `Pereira2018.243sentences-ridge` | 同registry ID / 1 | `Pereira2018.language`，选experiment=243sentences，dropna neuroid；保留story、passage_label、passage_index、stimulus_id | 每passage一次digest_text；language_system/fMRI；按story的10折GroupKFold |
| `Pereira2018.384sentences-ridge` | 同registry ID / 1 | 同上，选384sentences | 同上 |
| `Fedorenko2016-ridge` | 同registry ID / 3 | `Fedorenko2016.language`；保留sentence_id、stimulus_id、subject_UID | 每sentence一次digest_text，词是part；language_system/ECoG；按sentence_id的10折GroupKFold |
| `Blank2014-ridge` | 同registry ID / 1 | `Blank2014.fROI`；保留story、stimulus_id、subject_id | 每story一次digest_text；language_system/fMRI；按story的8折GroupKFold |
| `Futrell2018-pearsonr` | 同registry ID / 1 | `Futrell2018`；word、word_within_sentence_id、subject_id、presentation元数据 | reading_times任务；全体word一次digest_text；剔除句首词，目标沿subject平均；绝对值Pearson，无回归/无模型CV |

**Freeman public 的 version 是1，不能从private实现复制3。** 上表中的 Vision registry ID 与对象identifier也不一致，manifest应各自保存。[Majaj实现][Vmajaj]、[Freeman public实现][Vfreemanpublic]、[Freeman预处理][Vfreeman]、[Pereira实现][Lpereira]、[Fedorenko实现][Lfedorenko]、[Blank实现][Lblank]、[Futrell实现][Lfutrell]

## 本地数据和 ceiling 注入

### Vision

直接构造 `NeuralBenchmark(identifier, assembly, similarity_metric, visual_degrees, number_of_trials, ceiling_func, version, parent, bibtex)`。`assembly`应是完成官方预处理的神经目标，且attrs中附本地 `stimulus_set`；stimulus_set保存相同stimulus_id到本地图片的映射。不能通过构造官方public factory后再覆盖assembly实现无下载，因为factory会先加载数据。构造NeuralBenchmark也会读取assembly的region/time_bin，故必须传已准备好的真实或合成对象。[构造与调用][Vneural]

目标均值和ceiling输入必须分开：预测目标是平均重复后的assembly，`internal_consistency`输入是仍保留repetition的assembly。Majaj先squeeze time_bin；Freeman先选时间窗再时间平均；两者之后的repetition平均与时间坐标都应沿用源码语义。使用 `average_repetition` 会保留attrs，简单 `groupby(stimulus_id).mean()`可能丢失分层元数据。[平均函数][Vneural]

注入已核验的本地ceiling时，建议本地子类覆盖 `ceiling` property返回注入的 `Score`，而不只提供lambda。上游Vision `BenchmarkBase._ceiling`被result_caching装饰并只以identifier为显式参数；不同数据子集共用官方ID，可能命中既有ceiling缓存。必须隔离缓存或使用包括数据hash的本地标识。[Vision基类][Vbase]

### Language

四个family的官方构造器都直接 `load_dataset`；Pereira还加载预计算S3 ceiling，Blank/Fedorenko会立刻执行昂贵的 `ExtrapolationCeiling`。它们没有公开的 `data=`、`ceiling=`参数。[Pereira][Lpereira]、[Blank][Lblank]、[Fedorenko][Lfedorenko]

推荐每family一个薄子类：自定义 `__init__` 注入 `data`、`metric`，调用 `brainscore_core.benchmarks.BenchmarkBase.__init__`设置准确identifier/version/parent/bibtex/ceiling，继承上游 `__call__`。Pereira必须先等价执行 `_load_data` 的实验筛选与dropna；若有非language atlas，还需保留它重用language presentation坐标的逻辑。另一可行方案是Pereira单独覆盖 `_load_data`、`_load_ceiling` 后调用原构造器。不要在整个进程里长时间替换 `load_dataset`，以免并发任务互相影响。

ceiling缺失时，可提供明确的 `raw_only`诊断结果或报缺少资产，不能注入1并输出“官方归一化分数”。合成测试用固定ceiling可以验证计算链，但产物须标synthetic，不能进正式成绩。真实ceiling必须记录来源、数据/协议hash和计算方法。

## 回归、切分、聚合和归一化

### Vision PLS

- `load_metric('pls', crossvalidation_kwargs=...)`建立 `CrossRegressedCorrelation`，内部 `PLSRegression(n_components=25, scale=False)`；scikit-learn其余默认值沿用锁定环境。不额外全局标准化、不自行降到较少components。[PLS实现][Vmetric]、[指标注册][Vmetricinit]
- 分组键是stimulus_id，默认10次、train_size=.9、test_size=None、random_state=1、kfold=False、unique_split_values=False；实际使用 `StratifiedShuffleSplit`。Majaj用object_name、Freeman用texture_type分层。它们是重复随机90/10评测，不是10折KFold。[切分实现][Vtransforms]
- 每fold按目标neuroid计算SciPy Pearson；先对neuroid取中位数，再对fold取均值。raw保留split×neuroid得分；Vision另存fold均值的标准误。不能先全局平方各neuroid再平均。[回归实现][Vmetric]、[聚合实现][Vtransforms]
- 内部一致性ceiling：按唯一repetition值50/50随机分半，各半按非repetition坐标平均；逐neuroid相关，经 `2r/(1+r)`修正；同样neuroid中位数、split均值。默认10次拆分，seed1。[ceiling实现][Vceiling]
- 最终分数 `raw_scalar**2 / ceiling_scalar`，保留raw、ceiling、原error；**此helper不裁剪到[0,1]**。[归一化实现][Vneural]

### Language neural ridge

- 当前不是直接调用sklearn `RidgeCV`。`ridge_pearsonr`使用 `RidgeGCVTorch(alphas=np.logspace(-3,3,7))`，默认float64、fit_intercept=True、alpha_per_target=False、scoring=None；训练侧GCV选alpha，测试侧不参与fit。该实现中心化X/y但不做单位方差缩放。[ridge实现][Lmetric]、[GCV实现][Lridge]
- 外层GroupKFold的shuffle=True、random_state=1234。Pereira/Fedorenko默认10折，Blank显式8折。split_coord分别为story/sentence_id/story。源码需要sklearn>=1.6；不能用旧GroupKFold删掉shuffle参数来“兼容”，因为会改变切分。[切分实现][Ltransforms]、[依赖声明][Lproject]
- XarrayRegression在fit前按stimulus_id排序source/target；预测输出保留source presentation坐标及target neuroid坐标。自定义batched Pearson在每个向量L2 norm上加 `1e-8`，因此与SciPy结果有微小差异。逐neuroid中位数后按fold均值。[回归/相关实现][Lmetric]
- 每个layer独立评分和归一化，最后平均各layer分数。多层输入既不是自动取最佳层，也不是把多层特征合并成一次回归。首轮建议显式提交单层，层搜索另作为训练/验证阶段。[Pereira调用][Lpereira]、[Fedorenko调用][Lfedorenko]、[Blank调用][Lblank]
- 归一化 `raw / ceiling`，越界裁剪到0或1，同时保存 `original_out_of_range_score`；顶层结果另存layer_scores、raw、ceiling。[Language归一化][Lnormalize]
- Pereira默认使用预计算ceiling；Blank/Fedorenko用ExtrapolationCeiling，分别按subject_id/subject_UID，遍历受试者子集并以100次bootstrap拟合外推。它不是简单重复split-half。重新采样或换协议后不能沿用原ceiling声称同分数语义。[Pereira][Lpereira]、[外推ceiling][Lextrapolation]

### Futrell

这里的 `pearsonr` 指标返回 **abs(r)**，signed r和p保存在 `attrs['rvalue']`、`attrs['pvalue']`。因此实现既要复现官方abs分数，也应把符号留下供审计，不应把负相关伪装成正向生理解释。[Pearson实现][Lpearson]

Futrell没有拟合、没有外层CV：预测与目标都剔除 `word_within_sentence_id == 1`，目标沿subject平均，再算abs(Pearson)。ceiling按subject_id拆分，RandomState(0)、10次、每半先平均subject，再用同一abs(Pearson)指标；做Spearman–Brown修正，最后对10次结果取**中位数**。保留raw split值和uncorrected_consistencies。[Futrell实现][Lfutrell]

## 可保留官方运算的 trace hook

Vision、Language neural都可在当前metric实例包装 `apply(source_train, target_train, source_test, target_test)`。这是官方CV已经完成切分之后的边界，适合记录真实训练/测试stimulus_id、group值、模型layer、feature数、target neuroid_id。包装应调用原apply一次，不自行重新随机切分。若要记录prediction，包装该实例的 `regression.predict` 或 `correlation`；不要为了trace重复fit。[Vision apply][Vmetric]、[Language apply][Lmetric]

同时包装candidate的 `start_recording/start_neural_recording`、`look_at/digest_text`，记录time_bin、visual_degrees、输入顺序、context边界、输出shape和坐标hash。trace中的“已记录”和“经检查无交集”应分别表示；校验train/test的stimulus_id集合、分组集合，并检查源目标配对。Futrell没有fit trace，记录首词排除mask、subject平均、abs相关和signed r即可。

记录每fold选出的ridge `alpha_`以及输入/输出的shape/hash通常足以核验，不必默认序列化大系数矩阵。Language虽然提供 `store_regression_weights=True`，但当前底层是Torch ridge，系数维度/转设备与xarray打包需要专门验证后再使用。[可选权重记录][Lmetric]

## Vision pixels 与 AlexNet

`pixels`使用PIL打开本地图像、转RGB、resize到256×256，输出0–255像素值；层名为pixels。不是32×32、灰度、[0,1]或ImageNet归一化。直接缩小像素数能作为另一个baseline，但不能沿用官方pixels identity。[pixels实现][Vpixels]

AlexNet官方getter调用 `torchvision.models.alexnet(pretrained=True)`，会在缺少缓存时下载权重，因此离线执行应由调用侧加载已存在的明确权重并构造PytorchWrapper。官方预处理是 `Resize((224,224)) → ToTensor → Normalize(mean=.485,.456,.406; std=.229,.224,.225)`；**没有通常ImageNet recipe中的256缩放再center-crop**。PytorchWrapper在提取时调用eval并注册forward hooks。[AlexNet实现][Valexnet]、[图像预处理][Vpytorch]

官方候选层为features.2/.5/.7/.9/.12、classifier.2/.5。仓库当前AlexNet映射JSON为V1→features.2，V2/V4→features.7，IT→features.12；可以作为明确声明的固定参考映射，但并不证明这些层是在与本次public数据独立的资料上选出的。推荐本地baseline传显式region_layer_map，并标注映射来源/是否经过测试集选择。[映射][Valexnetmap]

`ModelCommitment`的默认visual_degrees是8；未提供映射时先找JSON，再回退在Freeman/Majaj的四个public benchmark自动选层。回退流程还会调用LayerPCA，因此不能用默认自动选层作为无下载、无泄漏的保障。[ModelCommitment][Vcommitment]、[选层][Vlayer]

屏幕处理在模型预处理之前：Freeman刺激4°匹配默认8°模型时要按上游place_on_screen添加灰色边框，再resize；Majaj8°匹配8°时不变。绕过此步直接抽图像特征会改变协议。缓存key至少包含图片hash、screen source/target degrees、resize/normalize、模型权重、layer以及软件版本。[屏幕处理][Vscreen]

## HuggingfaceSubject 精确行为

构造参数为 `HuggingfaceSubject(model_id, region_layer_mapping, model=None, tokenizer=None, use_localizer=False, localizer_kwargs=None, task_heads=None)`。应传入已在本地加载的model/tokenizer，避免内部from_pretrained；模型侧先eval，tokenizer侧显式设truncation_side='left'。wrapper对传入tokenizer不重设truncation_side，也没有为传入model调用eval。不要开启localizer，除非相应额外资产已准备并纳入协议。[HF实现][Lhf]

准确录制调用：`start_neural_recording(recording_target='language_system', recording_type='fMRI')` 用于Pereira/Blank；Fedorenko使用recording_type='ECoG'。Futrell调用 `start_behavioral_task('reading_times')`。这些值来自ArtificialSubject中的字符串常量。[接口][Lsubject]

`digest_text(list_of_parts)`每次调用重置context。每个part的上下文为从本次调用开始的累积parts，用单空格连接，删除空parts并消除标点前错误空格；用左侧截断tokenizer取有限上下文。神经输出是指定layer最后token的向量，对多层沿neuroid拼接并附layer坐标；后续benchmark仍逐层评分。[HF实现][Lhf]、[context函数][Lcontext]

因此Pereira以passage重置，Fedorenko以sentence重置，Blank以story重置；不能统一把所有sentence当互相独立单句。Futrell上游一次传入全部word，源码没有每story重置，复现模式必须保留；如果另做story-reset版本，应另命名协议。各family实现链接见上表。

默认reading-time head输出当前新增tokens的surprisal总和，单位bits，来自shifted logits cross entropy除log(2)，不是测得的毫秒。没有前文的单token输出NaN；多token首part会跳过无法预测的第一个token。Futrell排除所有句首词后再评分。只有纯行为、未设置neural_recordings的subject使用增量KV缓存；神经任务每次使用完整当前context。[HF实现][Lhf]

`start_neural_recording`是append而不是replace，重复复用一个subject会积累录制请求；behavioral_task也会保留。建议每benchmark新建轻量wrapper（底层本地model可以共享），明确设置一次任务，以避免重复hooks和行为/神经模式串扰。[HF实现][Lhf]

## 环境与待验收项

固定Language项目声明2.3.1，Python>=3.11、numpy<2、sklearn>=1.6、transformers>=4.51,<5。只固定两个domain SHA仍不足以完整复现，需记录brainscore-core、torch/torchvision、scipy、Pillow及result_caching版本。[项目依赖][Lproject]

RidgeGCVTorch的fit会重新按torch.cuda.is_available选择设备，即使构造时指定device；要确保CPU运行，应在独立进程设置可见设备策略并记录实际device/dtype。浮点微差的测试容差应与固定后端相匹配，不能把CPU/GPU结果强制bit-identical。[GCV fit][Lridge]

无需真实数据即可完成的验收包括：构造过程禁止网络、九ID预处理及录制参数契约、synthetic坐标乱序后正确对齐、分组不交叉、fold/neuroid聚合顺序、归一化边界、Futrell负r保留符号、重复运行不复用错误缓存、candidate录制状态隔离。真实任务仍待用户准备数据、刺激、权重与ceiling后执行完整下载hash验证、reference一致性和资源测量。本笔记没有宣称这些真实运行已完成。

## 原始对象锁与本地导入补充

静态提取产物：[bpb-bs-source-locks-20261111.json](/tmp/bpb-bs-source-locks-20261111.json)。从固定checkout的Python AST读取常量，没有import执行上游模块，没有请求S3或模型端点。文件包含六个来源、九个benchmark ID、16个原始对象，完整记录S3 bucket/key/version_id、原文件SHA1、来源文件SHA256和固定代码链接。HF模型revision/config由主任务另行核查，本文件没有重复发起查询。

| 来源 | 原始assembly文件 | 额外对象 | 本地导入要点 |
| --- | --- | --- | --- |
| MajajHong2015.public | `assy_dicarlo_MajajHong2015_public.nc` | `stimulus_hvm-public.csv`、`.zip` | .nc为data-only；CSV为分层/刺激元数据；ZIP为真实图像。V4/IT复用同一个原文件 |
| FreemanZiemba2013.public | `assy_movshon_FreemanZiemba2013_public.nc` | `stimulus_FreemanZiemba2013_aperture-public.csv`、`.zip` | 必须匹配aperture-public，不可换成noaperture/public刺激包；V1/V2复用同一原文件 |
| Pereira2018.language | `assy_Pereira2018_language.nc` | 243与384各一条三级ceiling链 | 243/384都从627条presentation的同一个assembly筛选，文本内嵌 |
| Fedorenko2016.language | `assy_Fedorenko2016_language.nc` | 无独立刺激包；ceiling需计算或用户提供已验证副本 | 文字与sentence_id内嵌，不能由文件存在推断ceiling就绪 |
| Blank2014.fROI | `assy_Blank2014_fROI.nc` | 无独立刺激包；ceiling需计算或用户提供已验证副本 | 文字与story元数据内嵌 |
| Futrell2018 | `assy_Futrell2018.nc` | 无独立刺激包；subject split-half ceiling由数据计算 | 单一原文件同时包含行为反应与词元数据 |

各来源具体hash与版本来自[Majaj数据注册][Dmajaj]、[Freeman数据注册][Dfreeman]、[Pereira数据注册][Dpereira]、[Fedorenko数据注册][Dfedorenko]、[Blank数据注册][Dblank]、[Futrell数据注册][Dfutrell]。对象路径按Language固定版[s3工具][Ls3]以及本地未修改Core `2e1cb4ea2708cb2a7df77b2a77bb1c10e445cb17`的[路径生成逻辑][Cs3]推导；路径并未远程探测。

**版本字段必须区分字符串 `"null"` 与JSON `null`。** Majaj public assembly和两套Vision刺激CSV/ZIP源码显式传字符串`"null"`；Freeman public assembly固定非空S3 version。四个Language assembly没有指定version，loader默认Python None，因此由SHA1约束内容而非显式S3版本。不要把这两种情况都转成缺失字段。

Pereira每个ridge版本的ceiling是三份文件：`ceiling_Pereira2018_{243|384}sentences-ridge.nc` → `ceiling_raw_...nc` → `ceiling_raw_raw_...nc`，逐级附在父Score的`attrs['raw']`。scalar归一化依赖第一份，但完整官方加载与ceiling审计包含三份。不要误用同目录legacy linear-shuffle的ceiling hash。[ceiling定义与递归加载][Lpereira]

导入时先校验原始文件字节SHA1，再加载。xarray重新保存的NetCDF、重新压缩的ZIP即使数据等价也可能hash不同，应标为派生文件并保留原件及变换记录；确认上游SHA1后可补本地SHA256和字节数。注册表不含逐图片hash与文件大小，JSON明确留空，不能编造。

Vision `.nc`的 `AssemblyLoader`可以独立加载，不需要图片；但完整 `load_dataset`还会调用刺激loader并用 `StimulusMergeAssemblyLoader`按stimulus_id合并CSV元数据，因此data-only不等于可直接执行。官方 `StimulusSetLoader`会检查CSV所指的每个图像文件：如果只导入CSV，应构造明确的metadata-only StimulusSet并合并，不能用不存在的图片路径声称image-ready。真实模型前向再要求对应ZIP已校验/解压且CSV路径与图像匹配。[Core assembly loader][Cassembly]、[Core stimulus loader][Cstimulus]

固定代码的许可检查：所检查六个family的Python/Markdown/文本源文件没有找到独立数据或刺激许可声明；两个仓库README的MIT声明只作为代码许可记录。Vision public名称、测试不带private_access、Freeman public模块允许本地评分的说明，支持其设计上的公开本地用途，但不等于图像/数据的再分发授权。Language测试没有private_access标记也不证明当前匿名访问必然成功。原发布者的进一步许可核查见下一节，locks本身不包含授权推断。[Vision说明][Vreadme]、[Language说明][Lreadme]、[Freeman public说明][Vfreemanpublic]

## 六个来源的数据、刺激许可与访问条件补充

核查日期：2026-11-11。本节仅查阅固定代码、作者发布页面、论文与公开项目元数据；没有请求Brain-Score数据端点，没有下载数据、刺激包或权重。结论分别对应代码、实验响应、刺激内容三个层次。`public`说明发布/访问设计，SHA1说明文件身份，这两者都不能代替原权利人的许可；没有查到明确许可也不等于已经证明禁止使用。

| 来源及实际资产 | 已核实的访问/发布声明 | 可确认的许可范围 | 尚需核实的边界 |
| --- | --- | --- | --- |
| **MajajHong2015.public**：神经assembly；`hvm-public` CSV/图像ZIP | DiCarlo官方数据页列为公开可下载assembly，并要求发表使用结果时引用Majaj et al. (2015)。页面说明assembly附刺激集。[作者数据页][RDiCarlo] | **公开发布＋引用要求明确，未找到明确的数据/图像许可证。** 固定注册和打包脚本没有补充许可。[注册][Dmajaj]、[打包][RPackMajaj] | 需要覆盖神经响应、刺激元数据及HVM图像的使用/再分发范围。不能因渲染图像或public命名推定图片无版权；也不把private benchmark样本的限制直接套给public包。 |
| **FreemanZiemba2013.public**：神经assembly；`FreemanZiemba2013.aperture-public` CSV/图像ZIP | 同一官方页列为公开assembly，并要求引用Freeman et al. (2013)；public benchmark源码明确用于本地原型/评分。[作者数据页][RDiCarlo]、[public说明][Vfreemanpublic] | **公开本地用途明确，未找到明确的数据/刺激许可证。** aperture处理脚本只说明图像变换，没有再许可条款。[注册][Dfreeman]、[aperture处理][RPackFreeman] | 原纹理/合成刺激与aperture派生图片的条款需分别覆盖；图像变换代码MIT不把输入图像变成MIT。 |
| **Pereira2018.language**：243/384共同assembly、内嵌句子；两组ceiling链 | 原论文Data availability指向作者OSF项目。官方API返回`public=true`；作者wiki把受试者数据指向Dropbox/Drive，材料另有OSF ZIP。[原论文][RPereiraPaper]、[项目API][RPereiraAPI]、[作者wiki][RPereiraWiki] | **公开访问有原作者声明，尚未确认独立的数据/句子许可。** 当前项目元数据为`node_license=null`；wiki没有许可声明；根目录只有材料ZIP，未见单独LICENSE元数据。[目录API][RPereiraFiles] | 不将论文的CC BY 4.0自动扩展到外链数据，亦不接受后续使用者对许可的转述作为原作者授权。Brain-Score打包还读取`Pereira2018_Blank`版本的`.mat`，需确认它与公开OSF数据及授权的对应关系；ceiling来源/派生记录也应保留。[打包][RPackPereira] |
| **Fedorenko2016.language**：ECoG assembly和内嵌实验句子 | 固定源码可定位`ecog-Fedorenko2016`的MATLAB输入及`sentences_8`文本；原论文/作者页面未给出已核实的开放数据许可证。[打包][RPackFedorenko]、[原论文][RFedorenkoPaper] | **神经数据和刺激许可仍未确认。** 代码中的S3 loader不构成原始数据授权，也不证明匿名下载当前可用。 | EvLab官方说明旧研究刺激/scripts及数据可联系作者；该说明是联系途径，不能当作此ECoG数据已获开放许可。[EvLab开放科学说明][REvOpen] 未替用户联系作者。 |
| **Blank2014.fROI**：fMRI time series、内嵌故事文字 | 固定打包读取`StoriesData_Dec2018`，并用`naturalistic_stories/all_stories.tok`匹配句子；story映射与Natural Stories十篇故事一致。[打包][RPackBlank] | **fMRI数据许可未确认；文本来源指向有CC BY-NC-SA 4.0许可的Natural Stories。** 后半项是打包源码的来源追踪，不是对当前assembly逐字节验证。[Natural Stories许可][RNaturalLicense]、[语料论文][RNaturalPaper] | 不能把文本许可扩展成神经数据许可。EvLab说明部分旧研究原始fMRI受IRB约束，通常能分享activation maps/fROI time series；这没有证明本assembly有同样限制，也没有授予再分发权。[EvLab说明][REvOpen] |
| **Futrell2018**：阅读时间及内嵌故事词元 | 作者公开`languageMIT/naturalstories`；原始2018论文明确语料含reading times和文字并以CC BY-NC-SA发布。固定打包读取同名`naturalstories_RTS/processed_RTs.csv`与`all_stories.tok`。[语料论文][RNaturalPaper]、[打包][RPackFutrell] | **原发布语料明确CC BY-NC-SA 4.0**；仓库LICENSE与论文声明互相支持。[固定LICENSE][RNaturalLicense] | 这是上游语料的许可证据，不能用Brain-Score MIT覆盖。应保留归属、许可及变换记录；另有下述数据版本缺口。 |

### 已明确的署名、非商业与派生要求

Natural Stories原语料（Futrell及Blank所引用的故事来源）应保留作者与来源信息、CC BY-NC-SA 4.0链接，并标明变换。许可限制商业用途；若对受许可材料作改编并发布，须遵守相同许可或兼容许可要求。该条件针对相关材料，不据此断言整个Bench程序或所有统计结果必须换许可证。当前作者README要求引用2021年期刊论文；Brain-Score注册保留2018语料论文引用，两条文献可同时保留。[作者README][RNaturalReadme]、[CC官方条款摘要][RCC]

平台的实际商业用途是否满足NC条件，没有在本次元数据审计中作结论；需要商用或重新发布语料时，这项条件不能留作“代码MIT已覆盖”。Majaj/Freeman作者明确要求引用原实验论文，但引用要求本身不等于完整的数据或图像许可。Pereira、Fedorenko和Blank神经数据未获得明确许可证据时，资产记录应保持“许可未核实”，不能标注为CC BY或MIT。

### Pereira许可证据和可复核快照

OSF项目`crwz7`的公开元数据、wiki文本、文件目录查询已存为本地证据：[OSF元数据快照](/tmp/bpb-bs-osf-pereira-license-metadata-20261111.json)。`node_license=null`仅说明本次查询没有项目级许可字段，不证明ZIP内部绝无许可证。由于用户禁止下载数据，本次未读取材料ZIP内部，也未进入受试者数据的Dropbox/Drive文件。根目录元数据显示`Pereira_Materials.zip`为289,933,079 bytes；这只是元数据，文件没有下载。[项目API][RPereiraAPI]、[目录API][RPereiraFiles]

OSF通用条款说明其对公开内容的使用许可不自动扩展到外链内容；因此作者wiki列出的外部受试者数据不能仅凭OSF平台条款判定已获得特定开放许可。未来核实应优先保存权利人对具体数据/句子及Brain-Score派生版本的声明，而非由论文开放获取标签推断。[OSF条款第5–6节][ROSFTerms]

### 独立缺口：Futrell阅读时间对齐版本

作者仓库固定commit `4700daad696e942f5aba23c957a7423d0de66612` 的README含 **2025-05-12更新**：原始SPR阅读时间发布存在一位错位，作者已修正当前仓库，建议既有使用者重新运行分析；其他类型数据不受该次修正影响。README另记录2020年Story 3对齐修正及2021年空词元RT删除。[作者更新记录][RNaturalReadme]

本次Brain-Score固定注册只提供Futrell assembly的SHA1，打包脚本没有锁定Natural Stories原始输入commit，也没有记录上述修正的应用状态。因此**不能判定本次pinned assembly已包含2025修正，也没有据此改动它**。不能通过把输出整体shift一位来猜测修正，更不能无记录替换成作者最新CSV并仍声称是同一benchmark。后续有数据后，需要核查打包原输入版本、逐`(item, zone)`映射与原作者修正说明；若需重打包，应建立新的数据版本、hash和reference结果。该缺口独立于许可状态，不由文件hash校验或合成测试消除。[Brain-Score固定注册][Dfutrell]、[打包脚本][RPackFutrell]

[RDiCarlo]: https://dicarlolab.mit.edu/brain-data-neurons-behavior-etc/
[RPackMajaj]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/data/majajhong2015/data_packaging/data_packaging.py
[RPackFreeman]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/data/freemanziemba2013/data_packaging/aperture_correct.py
[RPackPereira]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/data/pereira2018/data_packaging.py
[RPackFedorenko]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/data/fedorenko2016/data_packaging.py
[RPackBlank]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/data/blank2014/data_packaging.py
[RPackFutrell]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/data/futrell2018/data_packaging.py
[RPereiraPaper]: https://www.nature.com/articles/s41467-018-03068-4#data-availability
[RPereiraAPI]: https://api.osf.io/v2/nodes/crwz7/
[RPereiraWiki]: https://api.osf.io/v2/wikis/7y24k/content/
[RPereiraFiles]: https://api.osf.io/v2/nodes/crwz7/files/osfstorage/
[ROSFTerms]: https://osf.io/terms-of-use/
[RFedorenkoPaper]: https://pmc.ncbi.nlm.nih.gov/articles/PMC5068329/
[REvOpen]: https://www.evlab.mit.edu/open-science
[RNaturalLicense]: https://github.com/languageMIT/naturalstories/blob/4700daad696e942f5aba23c957a7423d0de66612/LICENSE.txt
[RNaturalReadme]: https://github.com/languageMIT/naturalstories/blob/4700daad696e942f5aba23c957a7423d0de66612/README.md
[RNaturalPaper]: https://aclanthology.org/L18-1012.pdf
[RCC]: https://creativecommons.org/licenses/by-nc-sa/4.0/

[Dmajaj]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/data/majajhong2015/__init__.py
[Dfreeman]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/data/freemanziemba2013/__init__.py
[Dpereira]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/data/pereira2018/__init__.py
[Dfedorenko]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/data/fedorenko2016/__init__.py
[Dblank]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/data/blank2014/__init__.py
[Dfutrell]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/data/futrell2018/__init__.py
[Ls3]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/utils/s3.py
[Cs3]: https://github.com/brain-score/core/blob/2e1cb4ea2708cb2a7df77b2a77bb1c10e445cb17/brainscore_core/supported_data_standards/brainio/s3.py
[Cassembly]: https://github.com/brain-score/core/blob/2e1cb4ea2708cb2a7df77b2a77bb1c10e445cb17/brainscore_core/supported_data_standards/brainio/assemblies.py
[Cstimulus]: https://github.com/brain-score/core/blob/2e1cb4ea2708cb2a7df77b2a77bb1c10e445cb17/brainscore_core/supported_data_standards/brainio/stimuli.py
[Vreadme]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/README.md
[Lreadme]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/README.md
[Vmajaj]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/majajhong2015/benchmark.py
[Vfreemanpublic]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/freemanziemba2013/benchmarks/public_benchmarks.py
[Vfreeman]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/freemanziemba2013/benchmarks/benchmark.py
[Vneural]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmark_helpers/neural_common.py
[Vbase]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/__init__.py
[Vmetric]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/metrics/regression_correlation/metric.py
[Vmetricinit]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/metrics/regression_correlation/__init__.py
[Vtransforms]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/metric_helpers/transformations.py
[Vceiling]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/metrics/internal_consistency/ceiling.py
[Vpixels]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/models/pixels/model.py
[Valexnet]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/models/alexnet/model.py
[Valexnetmap]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/models/alexnet/region_layer_map/alexnet.json
[Vpytorch]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/model_helpers/activations/pytorch.py
[Vcommitment]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/model_helpers/brain_transformation/__init__.py
[Vlayer]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/model_helpers/brain_transformation/neural.py
[Vscreen]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmark_helpers/screen.py
[Lpereira]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/pereira2018/benchmark.py
[Lfedorenko]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/fedorenko2016/benchmark.py
[Lblank]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/blank2014/benchmark.py
[Lfutrell]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/futrell2018/benchmark.py
[Lmetric]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/metrics/linear_predictivity/metric.py
[Lridge]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/metrics/linear_predictivity/ridgecv_gpu.py
[Ltransforms]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/utils/transformations.py
[Lnormalize]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/utils/ceiling.py
[Lextrapolation]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/blank2014/ceiling.py
[Lpearson]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/metrics/pearson_correlation/metric.py
[Lhf]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/model_helpers/huggingface.py
[Lsubject]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/artificial_subject.py
[Lcontext]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/model_helpers/preprocessing.py
[Lproject]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/pyproject.toml
