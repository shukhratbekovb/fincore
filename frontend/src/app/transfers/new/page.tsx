import { Suspense } from "react";
import { TransferForm } from "@/components/transfer";
export default function Page() {
  return (
    <Suspense fallback={<p>Загрузка формы…</p>}>
      <TransferForm />
    </Suspense>
  );
}
