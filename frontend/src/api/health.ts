export interface HealthResponse {
  status: "ready" | "unavailable";
  checks: { database: "ok" | "unavailable"; queue: "ok" | "unavailable" };
  ai: "disabled";
}

export function checkHealth(): Promise<HealthResponse> {
  // #ifdef MP-WEIXIN
  if (!import.meta.env.VITE_API_BASE_URL?.startsWith("https://")) {
    return Promise.reject(new Error("请先配置后端 HTTPS 地址与微信合法域名。"));
  }
  // #endif
  const base = import.meta.env.VITE_API_BASE_URL || "";
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${base}/api/v1/health/ready/`,
      method: "GET",
      timeout: 8000,
      success(response) {
        const data = response.data as Partial<HealthResponse> | undefined;
        if (
          response.statusCode === 200 &&
          data?.status === "ready" &&
          data.checks
        ) {
          resolve(data as HealthResponse);
        } else {
          reject(new Error("服务暂未就绪，请稍后重试。"));
        }
      },
      fail() {
        reject(new Error("暂时无法连接服务，请检查网络或后端状态。"));
      },
    });
  });
}
