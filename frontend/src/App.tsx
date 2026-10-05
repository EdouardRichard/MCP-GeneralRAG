import { Routes, Route, Link } from 'react-router-dom';
import { ConfigProvider, Layout, Radio } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import DomainProfilesPage from './pages/DomainProfilesPage';
import MemoriesPage from './pages/MemoriesPage';
import { LocaleProvider, useLocale } from './i18n';
import type { Locale } from './i18n';

const { Header, Content } = Layout;

function AppShell() {
  const { locale, setLocale, t } = useLocale();

  return (
    <ConfigProvider locale={locale === 'zh' ? zhCN : enUS}>
      <Layout style={{ minHeight: '100vh' }}>
        <Header
          style={{
            color: '#fff',
            fontSize: 20,
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingInline: 24,
            flexWrap: 'wrap',
            gap: 12,
            height: 'auto',
            minHeight: 64,
            lineHeight: '1.5',
            paddingBlock: 12,
          }}
        >
          <span>{t('common.appTitle')}</span>
          <Radio.Group
            size="small"
            value={locale}
            onChange={(e) => setLocale(e.target.value as Locale)}
            optionType="button"
            buttonStyle="solid"
            style={{ color: '#fff' }}
            options={[
              { label: '中文', value: 'zh' },
              { label: 'EN', value: 'en' },
            ]}
          />
        </Header>
        <nav style={{ display: 'flex', flexWrap: 'wrap', gap: 24, padding: '12px 24px', background: '#fff', borderBottom: '1px solid #e5e7eb' }}>
          <Link to="/">{t('projects.title')}</Link>
          <Link to="/domain-profiles">{t('domainProfiles.title')}</Link>
          <Link to="/memories">{t('memories.title')}</Link>
        </nav>
        <Content style={{ padding: 24 }}>
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/projects/:id" element={<ProjectDetailPage />} />
            <Route path="/domain-profiles" element={<DomainProfilesPage />} />
            <Route path="/memories" element={<MemoriesPage />} />
          </Routes>
        </Content>
      </Layout>
    </ConfigProvider>
  );
}

export default function App() {
  return (
    <LocaleProvider>
      <AppShell />
    </LocaleProvider>
  );
}
