interface ImportMetaEnv {
  readonly VITE_APP_VERSION: string;
  readonly VITE_SOURCE_REVISION: string;
  readonly VITE_SOURCE_TREE_DIRTY: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
