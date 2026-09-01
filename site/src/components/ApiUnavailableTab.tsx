import { EmptyState, PageIntro } from './ui';

export function ApiUnavailableTab({ title, description }: { title: string; description: string }) {
  return (
    <div className="page-container" data-data-mode="api">
      <PageIntro eyebrow="Публичный режим" title={title} description={description} />
      <div className="mt-10">
        <EmptyState
          title="Раздел пока не подключён к public API"
          description="В API-режиме здесь не используются demo-данные. Доступны каталог, источники и карточки опубликованных программ."
        />
      </div>
    </div>
  );
}
