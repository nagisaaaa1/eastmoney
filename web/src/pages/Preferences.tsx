import { useState, useEffect } from 'react';
import {
    Box,
    Typography,
    Paper,
    Button,
    TextField,
    Select,
    MenuItem,
    FormControl,
    InputLabel,
    Chip,
    Switch,
    FormControlLabel,
    Slider,
    Alert,
    Snackbar,
    CircularProgress,
    InputAdornment,
    Accordion,
    AccordionSummary,
    AccordionDetails,
    Autocomplete,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import SaveIcon from '@mui/icons-material/Save';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import TuneIcon from '@mui/icons-material/Tune';
import SecurityIcon from '@mui/icons-material/Security';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import FilterListIcon from '@mui/icons-material/FilterList';
import { getUserPreferences, saveUserPreferences, getPreferencePresets, type UserPreferences } from '../api';

// 常量定义
const RISK_LEVELS = [
    { value: 'conservative', label: '保守型', icon: '🛡️', color: 'success' },
    { value: 'moderate', label: '稳健型', icon: '⚖️', color: 'info' },
    { value: 'aggressive', label: '积进型', icon: '📈', color: 'warning' },
    { value: 'speculative', label: '投机型', icon: '🚀', color: 'error' },
] as const;

const INVESTMENT_HORIZONS = [
    { value: 'short_term', label: '短期 (7-30天)' },
    { value: 'medium_term', label: '中期 (1-6月)' },
    { value: 'long_term', label: '长期 (6月+)' },
] as const;

const INVESTMENT_GOALS = [
    { value: 'capital_preservation', label: '保本' },
    { value: 'steady_income', label: '稳定收益' },
    { value: 'capital_appreciation', label: '资本增值' },
    { value: 'speculation', label: '投机' },
] as const;

const INVESTMENT_STYLES = [
    { value: 'value', label: '价值投资' },
    { value: 'growth', label: '成长投资' },
    { value: 'blend', label: '均衡' },
    { value: 'momentum', label: '动量投资' },
    { value: 'dividend', label: '股息投资' },
] as const;

const SECTORS = [
    '科技', '医药', '消费', '金融', '工业', '能源', '材料', '房地产',
    '公用事业', '通信', '军工', '新能源', '芯片', '互联网'
];

const FUND_TYPES = ['股票型', '混合型', '指数型', '债券型', 'ETF', 'QDII'];

export default function PreferencesPage() {
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [preferences, setPreferences] = useState<Partial<UserPreferences>>({});
    const [presets, setPresets] = useState<Record<string, UserPreferences>>({});
    const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
        open: false,
        message: '',
        severity: 'success'
    });

    useEffect(() => {
        loadPreferences();
        loadPresets();
    }, []);

    const loadPreferences = async () => {
        try {
            const data = await getUserPreferences();
            setPreferences(data.preferences);
        } catch (error) {
            console.error('Failed to load preferences:', error);
        } finally {
            setLoading(false);
        }
    };

    const loadPresets = async () => {
        try {
            const data = await getPreferencePresets();
            setPresets(data.presets);
        } catch (error) {
            console.error('Failed to load presets:', error);
        }
    };

    const handleApplyPreset = (presetKey: string) => {
        if (presets[presetKey]) {
            setPreferences(presets[presetKey]);
            setSnackbar({
                open: true,
                message: `已应用 ${RISK_LEVELS.find(r => r.value === presetKey)?.label} 模板`,
                severity: 'success'
            });
        }
    };

    const handleSave = async () => {
        try {
            setSaving(true);
            await saveUserPreferences(preferences);
            setSnackbar({
                open: true,
                message: '投资偏好保存成功！',
                severity: 'success'
            });
        } catch (error) {
            console.error('Failed to save preferences:', error);
            setSnackbar({
                open: true,
                message: '保存失败，请重试',
                severity: 'error'
            });
        } finally {
            setSaving(false);
        }
    };

    const handleReset = () => {
        loadPreferences();
        setSnackbar({
            open: true,
            message: '已重置为上次保存的设置',
            severity: 'info'
        });
    };

    const updatePreference = <K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) => {
        setPreferences(prev => ({ ...prev, [key]: value }));
    };

    if (loading) {
        return (
            <Box className="flex items-center justify-center h-full">
                <CircularProgress />
            </Box>
        );
    }

    return (
        <Box className="flex flex-col gap-6 w-full h-full pb-10">
            {/* Header */}
            <Box className="flex justify-between items-center">
                <Box className="flex items-center gap-3">
                    <Box className="w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-pink-600 flex items-center justify-center shadow-lg">
                        <TuneIcon className="text-white" />
                    </Box>
                    <Box>
                        <Typography variant="h5" className="font-extrabold text-slate-800 tracking-tight">
                            个性化投资偏好
                        </Typography>
                        <Typography variant="body2" className="text-slate-500">
                            配置您的投资偏好，获取个性化推荐
                        </Typography>
                    </Box>
                </Box>
                <Box className="flex gap-2">
                    <Button
                        variant="outlined"
                        startIcon={<RestartAltIcon />}
                        onClick={handleReset}
                        disabled={saving}
                    >
                        重置
                    </Button>
                    <Button
                        variant="contained"
                        startIcon={saving ? <CircularProgress size={20} color="inherit" /> : <SaveIcon />}
                        onClick={handleSave}
                        disabled={saving}
                        className="bg-gradient-to-r from-purple-600 to-pink-600"
                    >
                        {saving ? '保存中...' : '保存设置'}
                    </Button>
                </Box>
            </Box>

            {/* Quick Presets */}
            <Paper elevation={0} className="p-6 border border-slate-200 rounded-xl">
                <Box className="flex items-center gap-2 mb-4">
                    <SecurityIcon className="text-slate-400" />
                    <Typography variant="h6" className="font-bold text-slate-800">
                        快速选择风险模板
                    </Typography>
                </Box>
                <Typography variant="body2" className="text-slate-500 mb-4">
                    根据您的风险承受能力，选择一个预设模板作为起点
                </Typography>
                <Box className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    {RISK_LEVELS.map((level) => (
                        <Paper
                            key={level.value}
                            elevation={preferences.risk_level === level.value ? 4 : 0}
                            className={`p-4 cursor-pointer transition-all border-2 ${
                                preferences.risk_level === level.value
                                    ? 'border-purple-500 bg-purple-50'
                                    : 'border-slate-200 hover:border-purple-300'
                            }`}
                            onClick={() => handleApplyPreset(level.value)}
                        >
                            <Box className="text-center">
                                <Typography className="text-3xl mb-2">{level.icon}</Typography>
                                <Typography variant="h6" className="font-bold mb-1">{level.label}</Typography>
                                <Typography variant="caption" className="text-slate-500">
                                    {level.value === 'conservative' && '追求本金安全，低风险'}
                                    {level.value === 'moderate' && '平衡风险与收益'}
                                    {level.value === 'aggressive' && '追求较高收益'}
                                    {level.value === 'speculative' && '追求高收益，高风险'}
                                </Typography>
                            </Box>
                        </Paper>
                    ))}
                </Box>
            </Paper>

            {/* Basic Settings */}
            <Accordion defaultExpanded>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box className="flex items-center gap-2">
                        <TrendingUpIcon className="text-blue-500" />
                        <Typography variant="h6" className="font-bold">投资基本信息</Typography>
                    </Box>
                </AccordionSummary>
                <AccordionDetails>
                    <Box className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <FormControl fullWidth>
                            <InputLabel>投资期限</InputLabel>
                            <Select
                                value={preferences.investment_horizon || 'medium_term'}
                                onChange={(e) => updatePreference('investment_horizon', e.target.value as any)}
                                label="投资期限"
                            >
                                {INVESTMENT_HORIZONS.map((option) => (
                                    <MenuItem key={option.value} value={option.value}>
                                        {option.label}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>

                        <FormControl fullWidth>
                            <InputLabel>投资目标</InputLabel>
                            <Select
                                value={preferences.investment_goal || 'capital_appreciation'}
                                onChange={(e) => updatePreference('investment_goal', e.target.value as any)}
                                label="投资目标"
                            >
                                {INVESTMENT_GOALS.map((option) => (
                                    <MenuItem key={option.value} value={option.value}>
                                        {option.label}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>

                        <FormControl fullWidth>
                            <InputLabel>投资风格</InputLabel>
                            <Select
                                value={preferences.investment_style || 'blend'}
                                onChange={(e) => updatePreference('investment_style', e.target.value as any)}
                                label="投资风格"
                            >
                                {INVESTMENT_STYLES.map((option) => (
                                    <MenuItem key={option.value} value={option.value}>
                                        {option.label}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>

                        <TextField
                            label="\u603b\u8d44\u91d1\uff08\u53ef\u9009\uff09"
                            type="number"
                            value={preferences.total_capital || ''}
                            onChange={(e) => updatePreference('total_capital', parseFloat(e.target.value) || undefined)}
                            InputProps={{
                                endAdornment: <InputAdornment position="end">\u5143</InputAdornment>
                            }}
                            helperText="\u4ec5\u7528\u4e8e\u9884\u7b97\u7ea6\u675f\uff1a\u53ef\u7528\u73b0\u91d1 = \u603b\u8d44\u91d1\uff08\u504f\u597d\uff09 - \u5f53\u524d\u6301\u4ed3\u5e02\u503c\uff08\u4e0d\u542b\u73b0\u91d1\uff09\uff1b\u6295\u8d44\u91d1\u989d\uff08\u603b\u6210\u672c\uff09\u7531\u4ea4\u6613\u8bb0\u5f55\u81ea\u52a8\u7d2f\u8ba1"
                            fullWidth
                        />
                    </Box>
                </AccordionDetails>
            </Accordion>

            {/* Risk Control */}
            <Accordion defaultExpanded>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box className="flex items-center gap-2">
                        <SecurityIcon className="text-orange-500" />
                        <Typography variant="h6" className="font-bold">风险控制</Typography>
                    </Box>
                </AccordionSummary>
                <AccordionDetails>
                    <Box className="space-y-4">
                        <Box>
                            <Typography variant="body2" className="mb-2">
                                最大回撤容忍度: {((preferences.max_drawdown_tolerance || 0.2) * 100).toFixed(0)}%
                            </Typography>
                            <Slider
                                value={(preferences.max_drawdown_tolerance || 0.2) * 100}
                                onChange={(_, value) => updatePreference('max_drawdown_tolerance', (value as number) / 100)}
                                min={5}
                                max={50}
                                step={5}
                                marks
                                valueLabelDisplay="auto"
                                valueLabelFormat={(value) => `${value}%`}
                            />
                        </Box>

                        <Box className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <TextField
                                label="止损比例"
                                type="number"
                                value={((preferences.stop_loss_percentage || 0.08) * 100).toFixed(0)}
                                onChange={(e) => updatePreference('stop_loss_percentage', parseFloat(e.target.value) / 100)}
                                InputProps={{
                                    endAdornment: <InputAdornment position="end">%</InputAdornment>
                                }}
                                fullWidth
                            />

                            <TextField
                                label="止盈比例（可选）"
                                type="number"
                                value={preferences.take_profit_percentage ? (preferences.take_profit_percentage * 100).toFixed(0) : ''}
                                onChange={(e) => updatePreference('take_profit_percentage', e.target.value ? parseFloat(e.target.value) / 100 : undefined)}
                                InputProps={{
                                    endAdornment: <InputAdornment position="end">%</InputAdornment>
                                }}
                                fullWidth
                            />

                            <TextField
                                label="单只标的最大仓位"
                                type="number"
                                value={((preferences.max_single_position || 0.15) * 100).toFixed(0)}
                                onChange={(e) => updatePreference('max_single_position', parseFloat(e.target.value) / 100)}
                                InputProps={{
                                    endAdornment: <InputAdornment position="end">%</InputAdornment>
                                }}
                                fullWidth
                            />
                        </Box>
                    </Box>
                </AccordionDetails>
            </Accordion>

            {/* Stock Filters */}
            <Accordion>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box className="flex items-center gap-2">
                        <FilterListIcon className="text-green-500" />
                        <Typography variant="h6" className="font-bold">选股偏好</Typography>
                    </Box>
                </AccordionSummary>
                <AccordionDetails>
                    <Box className="space-y-4">
                        <Box className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <TextField
                                label="最小市值"
                                type="number"
                                value={preferences.min_market_cap ? preferences.min_market_cap / 1e8 : ''}
                                onChange={(e) => updatePreference('min_market_cap', e.target.value ? parseFloat(e.target.value) * 1e8 : undefined)}
                                InputProps={{
                                    endAdornment: <InputAdornment position="end">亿</InputAdornment>
                                }}
                                fullWidth
                            />

                            <TextField
                                label="最大市值（可选）"
                                type="number"
                                value={preferences.max_market_cap ? preferences.max_market_cap / 1e8 : ''}
                                onChange={(e) => updatePreference('max_market_cap', e.target.value ? parseFloat(e.target.value) * 1e8 : undefined)}
                                InputProps={{
                                    endAdornment: <InputAdornment position="end">亿</InputAdornment>
                                }}
                                fullWidth
                            />

                            <TextField
                                label="最小PE（可选）"
                                type="number"
                                value={preferences.min_pe || ''}
                                onChange={(e) => updatePreference('min_pe', e.target.value ? parseFloat(e.target.value) : undefined)}
                                fullWidth
                            />

                            <TextField
                                label="最大PE（可选）"
                                type="number"
                                value={preferences.max_pe || ''}
                                onChange={(e) => updatePreference('max_pe', e.target.value ? parseFloat(e.target.value) : undefined)}
                                fullWidth
                            />
                        </Box>

                        <Box className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <FormControlLabel
                                control={
                                    <Switch
                                        checked={preferences.avoid_st_stocks ?? true}
                                        onChange={(e) => updatePreference('avoid_st_stocks', e.target.checked)}
                                    />
                                }
                                label="排除ST股票"
                            />

                            <FormControlLabel
                                control={
                                    <Switch
                                        checked={preferences.avoid_new_stocks ?? true}
                                        onChange={(e) => updatePreference('avoid_new_stocks', e.target.checked)}
                                    />
                                }
                                label="排除次新股"
                            />

                            <FormControlLabel
                                control={
                                    <Switch
                                        checked={preferences.require_profitable ?? true}
                                        onChange={(e) => updatePreference('require_profitable', e.target.checked)}
                                    />
                                }
                                label="要求盈利"
                            />
                        </Box>
                    </Box>
                </AccordionDetails>
            </Accordion>

            {/* Sector Preferences */}
            <Accordion>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box className="flex items-center gap-2">
                        <AccountBalanceIcon className="text-purple-500" />
                        <Typography variant="h6" className="font-bold">行业偏好</Typography>
                    </Box>
                </AccordionSummary>
                <AccordionDetails>
                    <Box className="space-y-4">
                        <Box>
                            <Typography variant="subtitle2" className="mb-2">偏好行业</Typography>
                            <Autocomplete
                                multiple
                                options={SECTORS}
                                value={preferences.preferred_sectors || []}
                                onChange={(_, newValue) => updatePreference('preferred_sectors', newValue)}
                                renderInput={(params) => <TextField {...params} placeholder="选择偏好的行业" />}
                                renderTags={(value, getTagProps) =>
                                    value.map((option, index) => (
                                        <Chip
                                            label={option}
                                            {...getTagProps({ index })}
                                            className="bg-green-100 text-green-700"
                                        />
                                    ))
                                }
                            />
                        </Box>

                        <Box>
                            <Typography variant="subtitle2" className="mb-2">排除行业</Typography>
                            <Autocomplete
                                multiple
                                options={SECTORS}
                                value={preferences.excluded_sectors || []}
                                onChange={(_, newValue) => updatePreference('excluded_sectors', newValue)}
                                renderInput={(params) => <TextField {...params} placeholder="选择要排除的行业" />}
                                renderTags={(value, getTagProps) =>
                                    value.map((option, index) => (
                                        <Chip
                                            label={option}
                                            {...getTagProps({ index })}
                                            className="bg-red-100 text-red-700"
                                        />
                                    ))
                                }
                            />
                        </Box>
                    </Box>
                </AccordionDetails>
            </Accordion>

            {/* Fund Preferences */}
            <Accordion>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box className="flex items-center gap-2">
                        <AccountBalanceIcon className="text-indigo-500" />
                        <Typography variant="h6" className="font-bold">基金偏好</Typography>
                    </Box>
                </AccordionSummary>
                <AccordionDetails>
                    <Box className="space-y-4">
                        <Box>
                            <Typography variant="subtitle2" className="mb-2">偏好基金类型</Typography>
                            <Autocomplete
                                multiple
                                options={FUND_TYPES}
                                value={preferences.preferred_fund_types || []}
                                onChange={(_, newValue) => updatePreference('preferred_fund_types', newValue)}
                                renderInput={(params) => <TextField {...params} placeholder="选择偏好的基金类型" />}
                                renderTags={(value, getTagProps) =>
                                    value.map((option, index) => (
                                        <Chip label={option} {...getTagProps({ index })} className="bg-blue-100 text-blue-700" />
                                    ))
                                }
                            />
                        </Box>

                        <Box className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <TextField
                                label="基金最小规模"
                                type="number"
                                value={preferences.min_fund_scale ? preferences.min_fund_scale / 1e8 : 1}
                                onChange={(e) => updatePreference('min_fund_scale', parseFloat(e.target.value) * 1e8)}
                                InputProps={{
                                    endAdornment: <InputAdornment position="end">亿</InputAdornment>
                                }}
                                fullWidth
                            />

                            <TextField
                                label="推荐基金数量"
                                type="number"
                                value={preferences.fund_recommendation_count || 5}
                                onChange={(e) => updatePreference('fund_recommendation_count', parseInt(e.target.value))}
                                fullWidth
                            />
                        </Box>
                    </Box>
                </AccordionDetails>
            </Accordion>

            {/* Snackbar */}
            <Snackbar
                open={snackbar.open}
                autoHideDuration={4000}
                onClose={() => setSnackbar({ ...snackbar, open: false })}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
            >
                <Alert severity={snackbar.severity} onClose={() => setSnackbar({ ...snackbar, open: false })}>
                    {snackbar.message}
                </Alert>
            </Snackbar>
        </Box>
    );
}
