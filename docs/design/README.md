# Визуальные направления FinCore / FinCore visual directions

[Русский](#ru) | [English](#en)

<a id="ru"></a>

## Русский

Дата: 16 октября 2026. Пользователь запросил оба варианта оформления, адаптацию для телефона и desktop, с Payme/Click как ориентирами. На том этапе финальный стиль и язык ещё не были выбраны; русский использован для обсуждения.

- [Светлый концепт](fincore-light-concept.png): светлые поверхности, бирюзовый акцент.
- [Тёмный концепт](fincore-dark-concept.png): графитовые поверхности, синий акцент.

Это предварительные растровые макеты, созданные встроенным image_gen. Они не подтверждают адаптивность, контраст или работоспособность интерфейса. Логотипы, даты, UUID и мелкие детали иллюстративны; в светлом макете источник top-up показан UUID, в реализации должен быть понятный label Sandbox. При разработке унифицировать логотип, структуру и компоненты обеих тем. [Полные промпты](prompts.md).

### Актуальные макеты v2

- [Светлая тема v2](fincore-light-v2.png).
- [Тёмная тема v2](fincore-dark-v2.png).

В каждом макете: desktop Главная и mobile Главная / Перевод / Профиль. Пять разделов навигации, три CAD-кошелька в карточках, общий баланс 1 250.00 CAD = 400 + 750 + 100. В форме показан новый внутренний перевод 50 CAD, ещё не выполненный; история содержит предыдущую операцию 100 CAD. Профиль показывает synthetic account, тему и выход. Системная тема — предложение UX.

Экраны Кошельки и История отдельно ещё не нарисованы; desktop Перевод и Профиль тоже требуют отдельной компоновки при разработке. На мобильной главной изображён частично видимый прокручиваемый контент; при вёрстке проверить нижний padding/safe area, чтобы последняя операция целиком прокручивалась выше навигации. Индикатор карусели и число карточек необходимо синхронизировать в реализации. Эти изображения — визуальные концепты, не интерактивный прототип и не проверка адаптивности.

Созданы встроенным image_gen; [промпты v2](prompts-v2.md). Версия v1 выше сохранена для сравнения.

### Реализованный интерфейс

Следующий этап выполнен: [Next.js frontend и результаты проверок](../frontend-implementation.md). В отчёте — реальные browser screenshots; исходные v2 изображения выше остаются дизайн-ориентирами.

### Адаптивное поведение

Требование пользователя: полноценная работа на телефоне и desktop. Предлагаемые правила реализации:

- 320–767 px: одна колонка, нижняя навигация, список операций вместо широкой таблицы, действия с touch target минимум 44×44 px.
- 768–1023 px: гибкая компоновка без горизонтального overflow; навигация выбирается по доступному месту.
- От 1024 px: боковая навигация, таблица истории, ограниченная ширина основного контента.
- Баланс и основной перевод доступны на всех размерах. Исходный концепт допускал полное копирование UUID при сокращённом отображении; текущие детали кошелька показывают и копируют номер кошелька.
- Нижняя навигация учитывает safe area, не перекрывает контент и формы при открытой клавиатуре.
- Проверить 320, 390, 768, 1024 и 1440 px, увеличение текста, keyboard focus и контраст в обеих темах.

Исходное предложение: после выбора визуального направления реализовать общий набор компонентов со светлой/тёмной палитрой и переключателем. На том этапе наличие обеих тем в конечном продукте ещё не было согласовано отдельно от запроса сравнить варианты.

### Ориентиры и scope

[Payme](https://p2p.payme.uz/ru) и [Click](https://click.uz/ru) использованы как продуктовые ориентиры переводов и доступных действий. Макеты не являются точными копиями их экранов. После [согласованного изменения](../scope-update-2026-10-16.md) нужны несколько CAD wallets в карточках и пять разделов, включая Перевод и Профиль. Картинки v1 показывают предыдущую структуру; v2 отражает новую навигацию и несколько кошельков. Это не финальные макеты. Исходный дизайн использовал wallet ID для переводов; текущий поиск получателя принимает номер кошелька и находит UUID внутри. История и sandbox-индикация сохраняются. Карты, оплата услуг, cashback и QR не добавляются этим дизайн-предложением.

<a id="en"></a>

## English

Date: 16 October 2026. The user requested both visual directions, mobile and desktop layouts, with Payme/Click as references. At that stage, the final style and language had not been selected; Russian was used for discussion.

- [Light concept](fincore-light-concept.png): light surfaces and a teal accent.
- [Dark concept](fincore-dark-concept.png): graphite surfaces and a blue accent.

These are preliminary raster mockups created with the built-in image_gen tool. They do not verify responsiveness, contrast or functional behavior. Logos, dates, UUIDs and small details are illustrative; the light mockup identifies the top-up source by UUID, whereas implementation should use a readable Sandbox label. Unify the logo, structure and components across both themes during development. [Full prompts](prompts.md).

### Updated v2 mockups

- [Light theme v2](fincore-light-v2.png).
- [Dark theme v2](fincore-dark-v2.png).

Each mockup includes desktop Home and mobile Home / Transfer / Profile. There are five navigation sections, three CAD wallet cards, and a total balance of CAD 1,250.00 = 400 + 750 + 100. The form shows a new CAD 50 internal transfer that has not yet executed; history includes a previous CAD 100 transaction. Profile shows a synthetic account, theme and logout. System theme is a UX proposal.

Wallets and History have not been drawn separately in these mockups; desktop Transfer and Profile also require separate layouts during development. The mobile home shows partially visible scrollable content; verify bottom padding/safe area so the last transaction can scroll fully above navigation. Keep carousel indicators and the number of cards synchronized. These images are visual concepts, not an interactive prototype or responsiveness verification.

Created with built-in image_gen; [v2 prompts](prompts-v2.md). The v1 images above are retained for comparison.

### Implemented interface

The next stage is complete: [Next.js frontend and verification results](../frontend-implementation.md). That report contains actual browser screenshots; the v2 source images remain design references.

### Responsive behavior

The user requires full mobile and desktop support. Proposed implementation rules:

- 320–767 px: one column, bottom navigation, transaction lists instead of wide tables, and touch targets of at least 44×44 px.
- 768–1023 px: flexible layout without horizontal overflow; navigation adapts to available space.
- 1024 px and above: side navigation, history table and constrained main content width.
- Balance and the main transfer action remain available at every size. The original concept allowed copying a full UUID even when displayed in shortened form; current wallet details display and copy the wallet number instead.
- Bottom navigation respects safe areas and does not cover content or forms when the keyboard opens.
- Check 320, 390, 768, 1024 and 1440 px, text enlargement, keyboard focus and contrast in both themes.

The original proposal was to implement shared components with light/dark palettes and a switch after selecting a direction. At that stage, delivering both themes had not been separately agreed beyond the request to compare alternatives.

### References and scope

[Payme](https://p2p.payme.uz/ru) and [Click](https://click.uz/ru) were product references for transfers and available actions. The mockups are not exact copies of their screens. The [approved scope change](../scope-update-2026-10-16.md) requires multiple CAD wallet cards and five sections, including Transfer and Profile. The v1 images show the previous structure; v2 reflects the new navigation and multiple wallets. These are not final mockups. The original transfer design used wallet IDs; current recipient lookup accepts a wallet number and resolves the UUID internally. History and sandbox indication remain. Bank cards, service payments, cashback and QR are not introduced by this design proposal.
