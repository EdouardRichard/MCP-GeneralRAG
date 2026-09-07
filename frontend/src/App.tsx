import { Routes, Route } from 'react-router-dom';
import { ConfigProvider, Layout, Radio } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import DomainProfilesPage from './pages/DomainProfilesPage';
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
        <Content style={{ padding: 24 }}>
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/projects/:id" element={<ProjectDetailPage />} />
            <Route path="/domain-profiles" element={<DomainProfilesPage />} />
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
