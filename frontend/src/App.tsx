import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './components/ui';
import { ConfirmProvider } from './components/ui';
import Admin from './pages/Admin';
import AdminDashboard from './pages/AdminDashboard';
import APIDocs from './pages/APIDocs';
import APIKeys from './pages/APIKeys';
import BackupDetail from './pages/BackupDetail';
import BackupSettingsPage from './pages/BackupSettingsPage';
import BackupsEnhanced from './pages/BackupsEnhanced';
import BucketDetail from './pages/BucketDetail';
import BugReports from './pages/BugReports';
import Containers from './pages/Containers';
import Groups from './pages/Groups';
import SystemRules from './pages/SystemRules';
import CreateInstance from './pages/CreateInstance';
import CustomImages from './pages/CustomImages';
import Dashboard from './pages/Dashboard';
import Endpoints from './pages/Endpoints';
import FileBrowser from './pages/FileBrowser';
import ImportExport from './pages/ImportExport';
import InstanceDetail from './pages/InstanceDetail';
import Login from './pages/Login';
import Networking from './pages/Networking';
import OAuthCallback from './pages/OAuthCallback';
import QuotaRequests from './pages/QuotaRequests';
import ResourceDetail from './pages/ResourceDetail';
import Resources from './pages/Resources';
import SecurityGroups from './pages/SecurityGroups';
import SSHKeys from './pages/SSHKeys';
import StatusPage from './pages/StatusPage';
import Storage from './pages/Storage';
import Templates from './pages/Templates';
import Tiers from './pages/Tiers';
import VMs from './pages/VMs';
import VPCs from './pages/VPCs';
import Volumes from './pages/Volumes';

function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
      <ConfirmProvider>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/oauth/callback" element={<OAuthCallback />} />
          <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
            <Route index element={<Dashboard />} />
            <Route path="resources" element={<Resources />} />
            <Route path="resources/:id" element={<ResourceDetail />} />
            <Route path="vms" element={<VMs />} />
            <Route path="vms/:id" element={<InstanceDetail />} />
            <Route path="containers" element={<Containers />} />
            <Route path="containers/:id" element={<InstanceDetail />} />
            <Route path="create-instance" element={<CreateInstance />} />
            <Route path="templates" element={<Templates />} />
            <Route path="volumes" element={<Volumes />} />
            <Route path="storage" element={<Storage />} />
            <Route path="storage/:bucketName" element={<FileBrowser />} />
            <Route path="storage/:bucketName/detail" element={<BucketDetail />} />
            <Route path="storage/:bucketName/files" element={<FileBrowser />} />
            <Route path="networks" element={<VPCs />} />
            <Route path="vpcs" element={<VPCs />} />
            <Route path="firewalls" element={<SecurityGroups />} />
            <Route path="security-groups" element={<SecurityGroups />} />
            <Route path="networking" element={<Networking />} />
            <Route path="endpoints" element={<Endpoints />} />
            <Route path="ssh-keys" element={<SSHKeys />} />

            <Route path="backups" element={<BackupsEnhanced />} />
            <Route path="backups/:backupId" element={<BackupDetail />} />
            <Route path="backups/settings" element={<BackupSettingsPage />} />
            <Route path="quota-requests" element={<QuotaRequests />} />
            <Route path="status" element={<StatusPage />} />
            <Route path="api-docs" element={<APIDocs />} />
            <Route path="import-export" element={<ImportExport />} />
            <Route path="bug-reports" element={<BugReports />} />
            <Route path="groups" element={<Groups />} />
            <Route path="keys" element={<APIKeys />} />
            <Route path="system-rules" element={<SystemRules />} />
            <Route path="tiers" element={<Tiers />} />
            <Route path="admin" element={<Admin />} />
            <Route path="admin/dashboard" element={<AdminDashboard />} />
            <Route path="admin/images" element={<CustomImages />} />
          </Route>
        </Routes>
      </AuthProvider>
      </ConfirmProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}

export default App;
