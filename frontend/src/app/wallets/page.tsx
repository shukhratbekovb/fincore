import { Suspense } from "react";
import { Wallets } from "@/components/wallets";
export default function Page() {
  return (
    <Suspense fallback={<p>Загрузка кошельков…</p>}>
      <Wallets />
    </Suspense>
  );
}
