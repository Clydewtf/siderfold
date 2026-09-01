import type {
  FiltersDto,
  FundingDto,
  ProgramDetailDto,
  ProgramListItemDto,
  PublicPageDto,
  SourceDto,
  SourceLinkDto,
  SourceRefDto,
  TaxonomyDto
} from './catalogApi';

export type PublicFunding = {
  kind: FundingDto['value_kind'];
  currencyCode: string | null;
  exactAmount: number | null;
  minAmount: number | null;
  maxAmount: number | null;
  label: string;
};

export type PublicSource = {
  id: string;
  name: string;
  canonicalUrl: string;
  publishedProgramCount: number | null;
};

export type PublicSourceLink = {
  source: PublicSource;
  sourceUrl: string;
  observedAt: string;
};

export type PublicProgram = {
  id: string;
  title: string;
  publicationStatus: 'published';
  publishedAt: string;
  updatedAt: string;
  deadline: string | null;
  funding: PublicFunding | null;
  primarySource: PublicSourceLink;
  sources: readonly PublicSourceLink[];
  regions: readonly string[];
  themes: readonly string[];
};

export type PublicCatalogFilters = {
  sources: readonly PublicSource[];
  regions: readonly TaxonomyDto[];
  themes: readonly TaxonomyDto[];
  fundingKinds: readonly FiltersDto['funding_kinds'][number][];
  deadline: FiltersDto['deadline'];
};

function amount(value: string | number | null, field: string): number | null {
  if (value === null) return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`Invalid public funding value: ${field}`);
  }
  return parsed;
}

function currencyLabel(currencyCode: string | null): string {
  if (currencyCode === 'RUB') return '₽';
  return currencyCode ?? '';
}

function money(value: number, currencyCode: string | null): string {
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)} ${currencyLabel(currencyCode)}`.trim();
}

export function fundingLabel(funding: FundingDto | null): string {
  if (!funding || funding.value_kind === 'not_stated') {
    return 'Сумма не указана';
  }
  if (funding.value_kind === 'unknown') return 'Сумма неизвестна';
  const exact = amount(funding.exact_amount, 'exact_amount');
  const minimum = amount(funding.min_amount, 'min_amount');
  const maximum = amount(funding.max_amount, 'max_amount');

  if (funding.value_kind === 'exact' && exact !== null) return money(exact, funding.currency_code);
  if (funding.value_kind === 'minimum' && minimum !== null) return `от ${money(minimum, funding.currency_code)}`;
  if (funding.value_kind === 'maximum' && maximum !== null) return `до ${money(maximum, funding.currency_code)}`;
  if (funding.value_kind === 'range' && minimum !== null && maximum !== null) {
    return `${money(minimum, funding.currency_code)} — ${money(maximum, funding.currency_code)}`;
  }
  throw new Error(`Funding values do not match ${funding.value_kind}.`);
}

function mapSource(source: SourceRefDto, publishedProgramCount: number | null = null): PublicSource {
  return {
    id: source.id,
    name: source.name,
    canonicalUrl: source.canonical_url,
    publishedProgramCount
  };
}

function mapSourceLink(link: SourceLinkDto): PublicSourceLink {
  return {
    source: mapSource(link.source),
    sourceUrl: link.source_url,
    observedAt: link.observed_at
  };
}

function mapFunding(funding: FundingDto | null): PublicFunding | null {
  if (!funding) return null;
  return {
    kind: funding.value_kind,
    currencyCode: funding.currency_code,
    exactAmount: funding.value_kind === 'exact' ? amount(funding.exact_amount, 'exact_amount') : null,
    minAmount: funding.value_kind === 'minimum' || funding.value_kind === 'range'
      ? amount(funding.min_amount, 'min_amount')
      : null,
    maxAmount: funding.value_kind === 'maximum' || funding.value_kind === 'range'
      ? amount(funding.max_amount, 'max_amount')
      : null,
    label: fundingLabel(funding)
  };
}

function mapProgramBase(program: ProgramListItemDto): PublicProgram {
  return {
    id: program.id,
    title: program.title,
    publicationStatus: program.publication_status,
    publishedAt: program.published_at,
    updatedAt: program.updated_at,
    deadline: program.deadline_on,
    funding: mapFunding(program.funding),
    primarySource: mapSourceLink(program.primary_source),
    sources: [mapSourceLink(program.primary_source)],
    regions: [],
    themes: []
  };
}

export function mapProgram(program: ProgramListItemDto): PublicProgram {
  return mapProgramBase(program);
}

export function mapProgramDetail(program: ProgramDetailDto): PublicProgram {
  return {
    ...mapProgramBase(program),
    sources: program.sources.map(mapSourceLink),
    regions: program.geographies.map((item) => item.name),
    themes: program.themes.map((item) => item.name)
  };
}

export function mapProgramPage(page: PublicPageDto<ProgramListItemDto>): {
  items: readonly PublicProgram[];
  page: number;
  pageSize: number;
  total: number;
} {
  return {
    items: page.items.map(mapProgram),
    page: page.page,
    pageSize: page.page_size,
    total: page.total
  };
}

export function mapSources(page: PublicPageDto<SourceDto>): {
  items: readonly PublicSource[];
  page: number;
  pageSize: number;
  total: number;
} {
  return {
    items: page.items.map((source) => mapSource(source, source.published_program_count)),
    page: page.page,
    pageSize: page.page_size,
    total: page.total
  };
}

export function mapFilters(filters: FiltersDto): PublicCatalogFilters {
  return {
    sources: filters.sources.map((source) => mapSource(source)),
    regions: filters.geographies,
    themes: filters.themes,
    fundingKinds: filters.funding_kinds,
    deadline: filters.deadline
  };
}
