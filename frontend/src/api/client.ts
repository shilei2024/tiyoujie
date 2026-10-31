import { clearSession, session, setLogin, type LoginResult } from "../state";

type Method = "GET" | "POST" | "DELETE";
interface Failure {
  error?: { message?: string };
}
let refreshing: Promise<void> | undefined;

function send<T>(
  path: string,
  method: Method,
  data?: object,
  token = session.access,
  headers: Record<string, string> = {},
): Promise<T> {
  // #ifdef MP-WEIXIN
  if (!import.meta.env.VITE_API_BASE_URL?.startsWith("https://")) {
    return Promise.reject(new Error("请先配置后端 HTTPS 地址与微信合法域名。"));
  }
  // #endif
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${import.meta.env.VITE_API_BASE_URL || ""}/api/v1/${path}`,
      method,
      data,
      header: {
        ...headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      timeout: 10000,
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.data as T);
        } else {
          const message =
            (response.data as Failure)?.error?.message ||
            "请求失败，请稍后重试。";
          reject(
            Object.assign(new Error(message), { status: response.statusCode }),
          );
        }
      },
      fail() {
        reject(new Error("连接失败，请检查网络或服务状态。"));
      },
    });
  });
}
export async function api<T>(
  path: string,
  method: Method = "GET",
  data?: object,
  headers: Record<string, string> = {},
): Promise<T> {
  try {
    return await send<T>(path, method, data, session.access, headers);
  } catch (error) {
    if ((error as { status?: number }).status !== 401 || !session.refresh)
      throw error;
    if (!refreshing) {
      refreshing = send<LoginResult>(
        "auth/refresh/",
        "POST",
        { refresh_token: session.refresh },
        "",
      )
        .then(setLogin)
        .catch(() => {
          clearSession();
          throw new Error("登录已失效，请重新登录。");
        })
        .finally(() => {
          refreshing = undefined;
        });
    }
    await refreshing;
    return send<T>(path, method, data, session.access, headers);
  }
}
export function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}
export function confirmAction(content: string): Promise<boolean> {
  return new Promise((resolve) =>
    uni.showModal({
      title: "请确认",
      content,
      confirmColor: "#2563eb",
      success: (result) => resolve(result.confirm),
      fail: () => resolve(false),
    }),
  );
}
export function familyQuery() {
  return `family_id=${encodeURIComponent(session.family?.id || "")}`;
}
export function secureTransport() {
  // #ifdef H5
  return (
    import.meta.env.VITE_API_BASE_URL || window.location.origin
  ).startsWith("https://");
  // #endif
  // #ifndef H5
  return import.meta.env.VITE_API_BASE_URL?.startsWith("https://") === true;
  // #endif
}
