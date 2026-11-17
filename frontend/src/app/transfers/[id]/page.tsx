import { TransferDetails } from "@/components/transfer";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <TransferDetails id={id} />;
}
