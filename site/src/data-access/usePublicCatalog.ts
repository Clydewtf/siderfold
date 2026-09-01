import { useCallback, useEffect, useState } from 'react';
import type { CatalogApiClient, ProgramQuery } from './catalogApi';
import { CatalogApiError, publicApiErrorMessage } from './catalogApi';
import {
  mapFilters,
  mapProgram,
  mapProgramDetail,
  mapProgramPage,
  mapSources,
  type PublicCatalogFilters,
  type PublicProgram,
  type PublicSource
} from './catalogMapper';

export type CatalogPage = {
  items: readonly PublicProgram[];
  page: number;
  pageSize: number;
  total: number;
};

export type SourcePage = {
  items: readonly PublicSource[];
  page: number;
  pageSize: number;
  total: number;
};

export type PublicCatalogState = {
  programs: CatalogPage | null;
  sources: SourcePage | null;
  filters: PublicCatalogFilters | null;
  programsLoading: boolean;
  metadataLoading: boolean;
  programsError: string | null;
  metadataError: string | null;
  query: ProgramQuery;
  setQuery: (query: ProgramQuery) => void;
  retry: () => void;
};

const initialQuery: ProgramQuery = {
  page: 1,
  pageSize: 20,
  sort: 'published_at',
  order: 'desc'
};

export function usePublicCatalog(client: CatalogApiClient): PublicCatalogState {
  const [query, setQuery] = useState<ProgramQuery>(initialQuery);
  const [programs, setPrograms] = useState<CatalogPage | null>(null);
  const [sources, setSources] = useState<SourcePage | null>(null);
  const [filters, setFilters] = useState<PublicCatalogFilters | null>(null);
  const [programsLoading, setProgramsLoading] = useState(true);
  const [metadataLoading, setMetadataLoading] = useState(true);
  const [programsError, setProgramsError] = useState<string | null>(null);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setProgramsLoading(true);
    setProgramsError(null);

    client.listPrograms(query, controller.signal)
      .then((page) => {
        if (active) setPrograms(mapProgramPage(page));
      })
      .catch((error: unknown) => {
        if (active) setProgramsError(publicApiErrorMessage(error, 'каталог'));
      })
      .finally(() => {
        if (active) setProgramsLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [client, query, retryToken]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setMetadataLoading(true);
    setMetadataError(null);

    Promise.all([
      client.listSources({ page: 1, pageSize: 100, sort: 'name', order: 'asc' }, controller.signal),
      client.getFilters(controller.signal)
    ])
      .then(([sourcePage, filterOptions]) => {
        if (!active) return;
        setSources(mapSources(sourcePage));
        setFilters(mapFilters(filterOptions));
      })
      .catch((error: unknown) => {
        if (active) setMetadataError(publicApiErrorMessage(error, 'фильтры'));
      })
      .finally(() => {
        if (active) setMetadataLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [client, retryToken]);

  const retry = useCallback(() => setRetryToken((value) => value + 1), []);

  return {
    programs,
    sources,
    filters,
    programsLoading,
    metadataLoading,
    programsError,
    metadataError,
    query,
    setQuery,
    retry
  };
}

export type PublicProgramState = {
  program: PublicProgram | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
};

export function usePublicProgram(client: CatalogApiClient, programId: string | null): PublicProgramState {
  const [program, setProgram] = useState<PublicProgram | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    if (!programId) {
      setProgram(null);
      setLoading(false);
      setError(null);
      return undefined;
    }

    const controller = new AbortController();
    let active = true;
    setProgram(null);
    setLoading(true);
    setError(null);

    client.getProgram(programId, controller.signal)
      .then((value) => {
        if (active) setProgram(mapProgramDetail(value));
      })
      .catch((reason: unknown) => {
        if (!active) return;
        if (reason instanceof CatalogApiError && reason.status === 404) {
          setError('Программа не найдена или ещё не опубликована.');
        } else {
          setError(publicApiErrorMessage(reason, 'карточку программы'));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [client, programId, retryToken]);

  const retry = useCallback(() => setRetryToken((value) => value + 1), []);

  return { program, loading, error, retry };
}
