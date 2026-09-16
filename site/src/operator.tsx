import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { OperatorApp } from './operator/OperatorApp';
import './styles.css';

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <OperatorApp />
  </StrictMode>
);
