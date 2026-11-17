# Frontend: реализация и проверка

Обновление 14 ноября 2026: frontend подключён к backend. Актуальные возможности,
настройки и проверки описаны в [frontend/README.md](../frontend/README.md).
Текст ниже — исторический отчёт об исходном локальном demo от 16 октября.

Дата: 16 октября 2026. Статус: локальный интерактивный demo готов; backend integration не выполнена.

## Принятый стек

Next.js App Router выбран пользователем. Реализация: Next.js 16, React 19, TypeScript, Tailwind CSS 4 и CSS variables, Lucide, next-themes, Zod и clsx. Тесты — Vitest и Playwright, форматирование — Prettier. Версии зафиксированы в `frontend/package-lock.json`. Команды сборки используют Webpack, поскольку Turbopack в текущей среде не может открыть внутренний порт для обработки CSS.

## Реализовано

Пять разделов, detail pages кошелька и операции, нижняя мобильная/боковая desktop навигация. Создание именованных CAD wallets с цветом; просмотр и копирование ID; локальные внутренние и внешние переводы через review/confirm; фильтры истории; light/dark/system theme; reset и выход из демо. Суммы разбираются в cents без parseFloat multiplication. Повтор локальной команды с тем же ключом не создаёт второе движение.

Demo state хранится в sessionStorage текущей вкладки, theme — в localStorage. Демо ограничено 12 кошельками и 1 000 операциями, external destination — специальным synthetic wallet. Это временные ограничения демо, не принятый backend contract. UI не вызывает API, не хранит auth tokens и не выполняет настоящих денежных операций.

## Выполненные проверки

Окружение: macOS, Node 20.20.2, npm 10.8.2, Google Chrome через Playwright.

| Проверка | Результат |
|---|---|
| `npm run typecheck` | Пройдена |
| `npm test` | 18 тестов пройдено |
| `npm run build` | Production build пройден |
| `npm run test:e2e` против production server | 3 сценария пройдено |
| `npm run format:check` | Пройдена |
| npm audit после обновления тестовых зависимостей | 0 известных уязвимостей на момент установки |

E2E охватывает создание wallet, перевод с проверкой результата, историю и фильтр, невалидные суммы, external demo recipient, сохранение темы, выход/повторный вход, перезагрузку и 25 сочетаний страниц/ширин: пять разделов × 320/390/768/1024/1440 px. Не обнаружено горизонтального overflow или pageerror в responsive run. Проверены снимки desktop/mobile и обеих тем. Это не полный accessibility audit, не проверка реальных устройств/клавиатуры телефона и не доказательство финансовой корректности backend.

## Снимки реализации

- [Главная desktop, светлая](design/implemented/home-desktop-light.png)
- [Главная desktop, тёмная](design/implemented/home-desktop-dark.png)
- [Главная mobile, светлая](design/implemented/home-mobile-light.png)
- [Главная mobile, тёмная](design/implemented/home-mobile-dark.png)
- [Перевод mobile](design/implemented/transfer-mobile.png)
- [Профиль mobile](design/implemented/profile-mobile.png)

Это реальные browser screenshots, не ImageGen. Full-page mobile screenshot фиксирует нижнюю навигацию на границе viewport; страница прокручивается под ней и имеет нижний отступ для последнего элемента.

## Следующий этап

Зафиксировать schemas API для нескольких wallets/aggregate/history, реализовать auth и заменить demo provider сетевым слоем. Добавить retry/unknown-outcome UX для реального HTTP и cursor pagination. Операторские пополнения остаются за рамками пользовательского демо. PostgreSQL/ledger tests и backend acceptance ACC не запускались.

Запуск и структура: [frontend README](../frontend/README.md).
