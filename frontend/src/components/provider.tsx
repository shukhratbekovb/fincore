"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ThemeProvider } from "next-themes";
import { z } from "zod";
import { api, ApiError } from "@/lib/api";
import {
  balanceSchema,
  transactionSchema,
  userSchema,
  walletSchema,
  type Balances,
  type Transaction,
  type User,
  type Wallet,
  type Page,
} from "@/lib/data";

type Context = {
  user: User | null;
  state: { wallets: Wallet[]; transactions: Transaction[] };
  balances: Balances;
  ready: boolean;
  error: string;
  notice: string;
  notify: (message: string) => void;
  reload: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  addWallet: (name: string, currency: Wallet["currency"]) => Promise<string>;
  walletAction: (
    id: string,
    action: "freeze" | "unfreeze" | "close" | "rename",
    name?: string,
  ) => Promise<void>;
  forget: () => void;
};
const FinCoreContext = createContext<Context | null>(null);
export function useFinCore() {
  const context = useContext(FinCoreContext);
  if (!context) throw new Error("Missing FinCore provider");
  return context;
}
function FinCoreProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [state, setState] = useState<Context["state"]>({
    wallets: [],
    transactions: [],
  });
  const [balances, setBalances] = useState<Balances>({ totals: [], as_of: "" });
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [notice, notify] = useState("");
  const generation = useRef(0);
  const forget = useCallback(() => {
    generation.current++;
    setUser(null);
    setState({ wallets: [], transactions: [] });
    setBalances({ totals: [], as_of: "" });
    setReady(true);
  }, []);
  const reload = useCallback(async () => {
    const current = ++generation.current;
    try {
      const [me, wallets, totals, history] = await Promise.all([
        api("users/me"),
        api("wallets"),
        api("users/me/balances"),
        api<Page<unknown>>("users/me/transactions?limit=20"),
      ]);
      const next = {
        user: userSchema.parse(me),
        wallets: z.array(walletSchema).parse(wallets),
        balances: balanceSchema.parse(totals),
        transactions: z.array(transactionSchema).parse(history.items),
      };
      if (current !== generation.current) return;
      setUser(next.user);
      setState({ wallets: next.wallets, transactions: next.transactions });
      setBalances(next.balances);
      setError("");
    } catch (failure) {
      if (current === generation.current) {
        if (failure instanceof ApiError && failure.status === 401) forget();
        else
          setError(
            failure instanceof z.ZodError
              ? "Ответ API не соответствует контракту. Обновите backend и повторите загрузку."
              : failure instanceof Error
                ? failure.message
                : "Не удалось загрузить данные.",
          );
      }
      throw failure;
    } finally {
      if (current === generation.current) setReady(true);
    }
  }, [forget]);
  useEffect(() => {
    void reload().catch(() => {});
    window.addEventListener("fincore:unauthorized", forget);
    return () => {
      generation.current++;
      window.removeEventListener("fincore:unauthorized", forget);
    };
  }, [reload, forget]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => notify(""), 6000);
    return () => clearTimeout(timer);
  }, [notice]);
  const value: Context = {
    user,
    state,
    balances,
    ready,
    error,
    notice,
    notify,
    reload,
    forget,
    login: async (username, password) => {
      await api("auth/login", { method: "POST", body: { username, password } });
      await reload();
    },
    logout: async () => {
      await api("auth/logout", { method: "POST", body: {} });
      forget();
    },
    addWallet: async (name, currency) => {
      const result = await api<{ wallet_id: string }>("wallets", {
        method: "POST",
        body: { name, currency },
      });
      await reload().catch(() => {});
      notify("Кошелёк создан");
      return result.wallet_id;
    },
    walletAction: async (id, action, name) => {
      await api(`wallets/${id}${action === "rename" ? "" : `/${action}`}`, {
        method: action === "rename" ? "PATCH" : "POST",
        body: action === "rename" ? { name } : {},
      });
      await reload().catch(() => {});
      notify("Кошелёк обновлён");
    },
  };
  return (
    <FinCoreContext.Provider value={value}>{children}</FinCoreContext.Provider>
  );
}
export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="data-theme" defaultTheme="light" enableSystem>
      <FinCoreProvider>{children}</FinCoreProvider>
    </ThemeProvider>
  );
}
