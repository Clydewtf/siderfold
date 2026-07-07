export type SourceType =
  | 'Фонд'
  | 'Госпрограмма'
  | 'Университет'
  | 'Акселератор'
  | 'Платформа'
  | 'Корпорация';

export type ProgramStatus = 'Открыта' | 'Скоро дедлайн' | 'Постоянный набор' | 'Ожидается' | 'Закрыта';

export type SupportType =
  | 'Грант'
  | 'Стипендия'
  | 'Акселерация'
  | 'Конкурс'
  | 'Обучение'
  | 'Инфраструктура';

export type Audience =
  | 'Студенты'
  | 'Исследователи'
  | 'Стартапы'
  | 'НКО'
  | 'Малый бизнес'
  | 'Университеты'
  | 'Креативные команды';

export type Topic =
  | 'Наука'
  | 'Образование'
  | 'Технологии'
  | 'Социальные проекты'
  | 'Культура'
  | 'Предпринимательство'
  | 'Экология'
  | 'ИИ'
  | 'Региональное развитие';

export type SupportSource = {
  id: string;
  name: string;
  type: SourceType;
  description: string;
  topics: readonly Topic[];
  region: string;
  websiteUrl: string;
  logoLabel: string;
  trustNote: string;
  featured: boolean;
};

export type SupportProgram = {
  id: string;
  sourceId: string;
  title: string;
  description: string;
  status: ProgramStatus;
  deadline: string | null;
  publishedAt: string;
  fundingAmountRub: number | null;
  fundingLabel: string;
  supportType: SupportType;
  audience: readonly Audience[];
  topics: readonly Topic[];
  region: string;
  requirements: readonly string[];
  sourceUrl: string;
  documentUrls: readonly string[];
  featured: boolean;
};

export type ProgramSort = 'deadline' | 'funding' | 'newest' | 'source';

export type DeadlineFilter = 'all' | 'withDeadline' | 'withoutDeadline' | 'next30' | 'next90';

export type ProgramFilters = {
  query: string;
  topic: Topic | 'Все тематики';
  supportType: SupportType | 'Все типы';
  audience: Audience | 'Все аудитории';
  status: ProgramStatus | 'Все статусы';
  deadline: DeadlineFilter;
  sort: ProgramSort;
};
