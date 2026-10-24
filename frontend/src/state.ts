import { reactive } from "vue";

export interface Family {
  id: string;
  name: string;
  owner_id: number;
  role: "guardian" | "student";
}
export interface LoginResult {
  access_token: string;
  refresh_token: string;
  user: { id: number; is_test_login: boolean };
}

// Session memory only. Provider keys never enter this state or persistent storage.
export const session = reactive({
  access: "",
  refresh: "",
  user: null as LoginResult["user"] | null,
  family: null as Family | null,
});
export function setLogin(result: LoginResult) {
  session.access = result.access_token;
  session.refresh = result.refresh_token;
  session.user = result.user;
}
export function clearSession() {
  session.access = "";
  session.refresh = "";
  session.user = null;
  session.family = null;
}
