export type TabId = 'home' | 'programs' | 'analytics' | 'sources' | 'profile';
export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';
export type CardDensity = 'comfortable' | 'compact';

export type DisplayPreferences = {
  density: CardDensity;
  showDataQuality: boolean;
  reduceMotion: boolean;
};

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

export type PersistedAppState = {
  theme: ThemePreference;
  favoriteProgramIds: readonly string[];
  favoriteSourceIds: readonly string[];
  recentProgramIds: readonly string[];
  preferredRegions: readonly string[];
  preferredTopics: readonly Topic[];
  display: DisplayPreferences;
};

export type BackendFeature =
  | 'signIn'
  | 'registration'
  | 'accountData'
  | 'notifications'
  | 'documents'
  | 'applications'
  | 'reportExport'
  | 'profileSync';

export type BackendNotice = { feature: BackendFeature; message: string };

export type AppState = PersistedAppState & {
  activeTab: TabId;
  selectedProgramId: string | null;
  backendNotice: BackendNotice | null;
};

export type CoverageLevel = 'federal' | 'regional' | 'municipal' | 'private';

export type CurrencyCode = 'RUB';

export type DataQualityField = 'funding' | 'deadline' | 'regions' | 'source' | 'updatedAt' | 'sourceUrl';

export type DataQualityLevel = 'high' | 'medium' | 'low';

export type DataQuality = {
  score: number;
  level: DataQualityLevel;
  missingFields: readonly DataQualityField[];
  checkedAt: string;
};

export type ProgramHistoryPoint = {
  year: number;
  fundingAmountRub: number | null;
  applicationsCount: number | null;
  winnersCount: number | null;
};

export type SupportSource = {
  id: string;
  name: string;
  type: SourceType;
  description: string;
  topics: readonly Topic[];
  region: string;
  coverageLevel: CoverageLevel;
  websiteUrl: string;
  logoLabel: string;
  trustNote: string;
  verifiedAt: string;
  featured: boolean;
};

export type SupportProgram = {
  id: string;
  sourceId: string;
  title: string;
  description: string;
  status: ProgramStatus;
  supportType: SupportType;
  topics: readonly Topic[];
  audience: readonly Audience[];
  regions: readonly string[];
  coverageLevel: CoverageLevel;
  launchYear: number;
  activeFrom: string;
  activeTo: string | null;
  deadline: string | null;
  fundingAmountRub: number | null;
  fundingMinRub: number | null;
  fundingMaxRub: number | null;
  fundingLabel: string;
  currency: CurrencyCode;
  requirements: readonly string[];
  sourceUrl: string;
  documentUrls: readonly string[];
  publishedAt: string;
  updatedAt: string;
  featured: boolean;
  dataQuality: DataQuality;
  history: readonly ProgramHistoryPoint[];
};

export type ProgramSort = 'deadline' | 'funding' | 'newest' | 'source' | 'relevance';

export type DeadlineFilter = 'all' | 'withDeadline' | 'withoutDeadline' | 'next30' | 'next90';

export type ActivePeriodFilter = 'all' | 'activeNow' | 'upcoming' | 'ended';

export type FundingFilter = 'all' | 'withFunding' | 'withoutFunding';

export type ProgramFilters = {
  query: string;
  region: string;
  coverageLevel: CoverageLevel | 'Все уровни';
  launchYear: number | 'Все годы';
  activePeriod: ActivePeriodFilter;
  funding: FundingFilter;
  fundingMinRub: number | null;
  fundingMaxRub: number | null;
  deadline: DeadlineFilter;
  status: ProgramStatus | 'Все статусы';
  topic: Topic | 'Все тематики';
  supportType: SupportType | 'Все типы';
  audience: Audience | 'Все аудитории';
  sourceId: string;
  sort: ProgramSort;
};

export type SourceFilters = {
  type: SourceType | 'Все типы';
  region: string;
  coverageLevel: CoverageLevel | 'Все уровни';
  topic: Topic | 'Все тематики';
};
