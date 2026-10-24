import { api } from "./client";
import { session } from "../state";

export interface TextVersion {
  id: string;
  number: number;
  origin: "manual" | "ocr";
  text: string;
  answer: string;
  confirmed: boolean;
  confidence: number | null;
  uncertainties: string[];
}
export interface Asset {
  id: string;
  width: number;
  height: number;
  byte_size: number;
  parent_id: string | null;
}
export interface Problem {
  id: string;
  child_id: string;
  source: string;
  chapter: string;
  knowledge_points: string[];
  error_type: string;
  mistake_date: string | null;
  revision: number;
  status: string;
  current_text: TextVersion | null;
  assets: Asset[];
}
export interface OCRJob {
  id: string;
  status: string;
  error_code: string;
  fee_status: string;
  billing_mode: string;
  cancel_requested: boolean;
}

function base() {
  // #ifdef MP-WEIXIN
  if (!import.meta.env.VITE_API_BASE_URL?.startsWith("https://"))
    throw new Error("请先配置 HTTPS 后端地址。");
  // #endif
  return import.meta.env.VITE_API_BASE_URL || "";
}
export async function uploadImage(problemId: string, filePath: string) {
  await api("auth/me/");
  return new Promise<Asset>((resolve, reject) =>
    uni.uploadFile({
      url: `${base()}/api/v1/problems/${problemId}/assets/`,
      filePath,
      name: "file",
      header: { Authorization: `Bearer ${session.access}` },
      timeout: 20000,
      success(response) {
        try {
          const data = JSON.parse(response.data);
          if (response.statusCode === 201) resolve(data as Asset);
          else reject(new Error(data?.error?.message || "图片上传失败。"));
        } catch {
          reject(new Error("图片上传响应无效，请重新载入检查。"));
        }
      },
      fail: () => reject(new Error("图片上传未完成，请重新载入检查后再试。")),
    }),
  );
}
export async function downloadImage(assetId: string) {
  await api("auth/me/");
  return new Promise<string>((resolve, reject) =>
    uni.downloadFile({
      url: `${base()}/api/v1/assets/${assetId}/content/`,
      header: { Authorization: `Bearer ${session.access}` },
      timeout: 15000,
      success(response) {
        if (response.statusCode === 200) resolve(response.tempFilePath);
        else reject(new Error("图片已不可访问或暂时不可用。"));
      },
      fail: () => reject(new Error("图片载入失败，请检查连接后重试。")),
    }),
  );
}
export function releaseImages(paths: string[]) {
  for (const path of paths) {
    // #ifdef H5
    if (path.startsWith("blob:")) URL.revokeObjectURL(path);
    // #endif
    // #ifdef MP-WEIXIN
    uni.getFileSystemManager().unlink({ filePath: path, fail: () => {} });
    // #endif
  }
}

// #ifdef H5
export async function cropBrowserImage(
  path: string,
  crop: { x: number; y: number; width: number; height: number },
  width: number,
  height: number,
) {
  const image = new Image();
  image.src = path;
  await image.decode();
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("当前浏览器无法生成裁剪预览。");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(
    image,
    crop.x,
    crop.y,
    crop.width,
    crop.height,
    0,
    0,
    width,
    height,
  );
  return canvas.toDataURL("image/jpeg", 0.9);
}
// #endif
