import type { BackendFeature } from '../types';

export type BackendCapability = {
  feature: BackendFeature;
  title: string;
  description: string;
  actionLabel: string;
  notice: string;
  surface: 'profile' | 'analytics';
};

type BackendCapabilityRegistry = {
  readonly [Feature in BackendFeature]: BackendCapability & { readonly feature: Feature };
};

const backendCapabilitiesByFeature = {
  signIn: { feature: 'signIn', title: 'Вход', description: 'Демо-режим без аккаунта.', actionLabel: 'Войти', notice: 'Вход будет доступен после подключения аккаунта.', surface: 'profile' },
  registration: { feature: 'registration', title: 'Регистрация', description: 'Демо-режим без создания аккаунта.', actionLabel: 'Зарегистрироваться', notice: 'Регистрация будет доступна после подключения аккаунта.', surface: 'profile' },
  accountData: { feature: 'accountData', title: 'Данные профиля', description: 'Имя и контакты требуют защищенного аккаунта.', actionLabel: 'Открыть данные профиля', notice: 'Пользовательские данные будут доступны после подключения аккаунта.', surface: 'profile' },
  notifications: { feature: 'notifications', title: 'Уведомления', description: 'Демо-режим: серверные напоминания о дедлайнах еще не подключены.', actionLabel: 'Настроить уведомления', notice: 'Уведомления появятся после подключения backend.', surface: 'profile' },
  documents: { feature: 'documents', title: 'Документы', description: 'Личное хранилище документов требует аккаунта.', actionLabel: 'Открыть документы', notice: 'Документы будут доступны после подключения аккаунта.', surface: 'profile' },
  applications: { feature: 'applications', title: 'Заявки', description: 'Отправка и статусы заявок требуют backend.', actionLabel: 'Открыть заявки', notice: 'Заявки будут доступны после подключения аккаунта и backend.', surface: 'profile' },
  reportExport: { feature: 'reportExport', title: 'Экспорт отчетов', description: 'Демо-режим без серверной подготовки файлов.', actionLabel: 'Экспортировать отчет', notice: 'Экспорт отчета и CSV появится после подключения backend.', surface: 'analytics' },
  profileSync: { feature: 'profileSync', title: 'Синхронизация', description: 'Демо-режим: настройки хранятся только на этом устройстве.', actionLabel: 'Синхронизировать профиль', notice: 'Синхронизация появится после подключения аккаунта и backend.', surface: 'profile' }
} as const satisfies BackendCapabilityRegistry;

export const BACKEND_CAPABILITIES = Object.freeze(
  Object.values(backendCapabilitiesByFeature)
) satisfies readonly BackendCapability[];

export function getBackendCapability(feature: BackendFeature): BackendCapability {
  return backendCapabilitiesByFeature[feature];
}
