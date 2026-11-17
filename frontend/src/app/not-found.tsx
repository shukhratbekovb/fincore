import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty-state">
      <h1>Страница не найдена</h1>
      <p>Вернитесь к своим кошелькам.</p>
      <Link className="button primary" href="/">
        На главную
      </Link>
    </div>
  );
}
