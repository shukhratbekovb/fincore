"use client";
import { useEffect, useState } from "react";
import { api } from "./api";
import { walletRecipientSchema, type WalletRecipient } from "./data";

export function useWalletRecipient(number: string, enabled: boolean) {
  const valid = /^[0-9]{20}$/.test(number);
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{
    number: string;
    recipient: WalletRecipient | null;
    error: string;
    loading: boolean;
  }>({ number: "", recipient: null, error: "", loading: false });
  useEffect(() => {
    if (!enabled || !valid) return;
    const controller = new AbortController();
    setState({ number, recipient: null, error: "", loading: true });
    const timer = setTimeout(async () => {
      try {
        const recipient = walletRecipientSchema.parse(
          await api("transfer-recipients/resolve", {
            method: "POST",
            body: { wallet_number: number },
            signal: controller.signal,
          }),
        );
        if (recipient.number !== number)
          throw new Error("Ответ поиска не соответствует введённому номеру.");
        if (!controller.signal.aborted)
          setState({ number, recipient, error: "", loading: false });
      } catch (failure) {
        if (!controller.signal.aborted)
          setState({
            number,
            recipient: null,
            error:
              failure instanceof Error
                ? failure.message
                : "Не удалось найти получателя.",
            loading: false,
          });
      }
    }, 400);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [number, enabled, valid, revision]);
  const current = enabled && valid && state.number === number;
  return {
    recipient: current ? state.recipient : null,
    error: current ? state.error : "",
    loading: enabled && valid && (!current || state.loading),
    retry: () => setRevision((value) => value + 1),
  };
}
