/**
 * data/types.ts — data.lock 数据子系统的承重墙接口。
 * 大数据集 body 永不进 git；data.lock 是内容寻址清单(name+uri+sha256+bytes+format)，
 * 按 scheme 懒拉取、sha256 校验、落本地内容寻址缓存。
 */

/** data.lock 里的一条数据集声明。 */
export interface DatasetEntry {
  /** 任务内唯一名（也用于 stage 时的目标文件名）。 */
  name: string;
  /** 内容来源；scheme 决定用哪个 fetcher：https:// / file:// / hf:// 。 */
  uri: string;
  /** 内容 sha256（64 位十六进制小写）——内容寻址 + 完整性校验的键。 */
  sha256: string;
  /** 期望字节数（用于进度/审计；下载后会与实际比对）。 */
  bytes: number;
  /** 格式标签（parquet/csv/nii.gz/...），仅元数据。 */
  format?: string;
}

/** 一个任务的 data.lock 解析结果。 */
export interface DataManifest {
  datasets: DatasetEntry[];
}

/** resolve 后的数据集：本地缓存绝对路径 + 原始声明。 */
export interface ResolvedDataset {
  entry: DatasetEntry;
  /** 内容寻址缓存里的绝对路径（已通过 sha256 校验）。 */
  path: string;
  /** 本次是否真的下载了（false = 缓存命中）。 */
  fetched: boolean;
}

/** fetcher 收到的请求：解析出的 uri + 目标落盘路径（由 cache 决定）。 */
export interface FetchRequest {
  uri: string;
  /** fetcher 应把内容写到这个绝对路径（cache 提供的临时路径）。 */
  destPath: string;
}

/** 一个 scheme 的拉取实现（对称于 scorer 注册表）。 */
export type Fetcher = (req: FetchRequest) => Promise<void>;
