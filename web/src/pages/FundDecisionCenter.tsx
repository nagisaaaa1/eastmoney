import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PsychologyAltIcon from '@mui/icons-material/PsychologyAlt';
import RefreshIcon from '@mui/icons-material/Refresh';
import SavingsIcon from '@mui/icons-material/Savings';
import FolderIcon from '@mui/icons-material/Folder';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';

import {
  createFundDCAPlan,
  createFundResearchBatchRecommendJob,
  fetchFundConstraintSuggestions,
  fetchFundDCAPlans,
  fetchFundDCARuns,
  fetchFundResearchBatchJob,
  fetchFundResearchFundContext,
  fetchFundResearchGlobalContext,
  fetchFundResearchUniverse,
  fetchDefaultPortfolio,
  fetchPortfolioSummaryNew,
  recommendFundResearch,
  runFundAISelection,
  simulateFundDCA,
  syncFundResearchUniverse,
  updateFundDCAPlan,
  type FundAISelectionResult,
  type FundConstraintSuggestion,
  type FundDCAPlan,
  type FundDCARun,
  type FundResearchBatchJob,
  type FundResearchRecommendation,
  type FundUniverseItem,
  type UnifiedPosition,
} from '../api';

const FINAL_JOB_STATUS = new Set(['completed', 'completed_with_errors', 'cancelled', 'failed']);
const TAB_KEYS = ['universe', 'ai', 'decision', 'trading'] as const;
type TabKey = (typeof TAB_KEYS)[number];

const parseNumber = (raw: string): number | undefined => {
  if (!raw.trim()) return undefined;
  const value = Number(raw);
  if (!Number.isFinite(value)) return undefined;
  return value;
};

const actionToText = (action?: string) => {
  if (action === 'add') return '加仓';
  if (action === 'hold') return '维持';
  if (action === 'pause') return '暂停';
  return '-';
};

const tabIndexFromKey = (key: string | null): number => {
  if (!key) return 0;
  const idx = TAB_KEYS.indexOf(key as TabKey);
  return idx >= 0 ? idx : 0;
};

export default function FundDecisionCenterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState(() => tabIndexFromKey(searchParams.get('tab')));
  const [analysisMode, setAnalysisMode] = useState<'quick' | 'deep'>('deep');

  const [topN, setTopN] = useState('8');
  const [candidateLimit, setCandidateLimit] = useState('30');
  const [baseAmount, setBaseAmount] = useState('30');
  const [maxSingleDay, setMaxSingleDay] = useState('');
  const [maxDrawdown, setMaxDrawdown] = useState('35');
  const [tacticalBoost, setTacticalBoost] = useState(true);

  const [singleCode, setSingleCode] = useState('');
  const [newPlanCode, setNewPlanCode] = useState('');
  const [newPlanAmount, setNewPlanAmount] = useState('30');
  const [newPlanFreq, setNewPlanFreq] = useState<'daily' | 'weekly' | 'monthly'>('daily');

  const [selection, setSelection] = useState<FundAISelectionResult | null>(null);
  const [constraintSuggestion, setConstraintSuggestion] = useState<FundConstraintSuggestion | null>(null);
  const [globalContext, setGlobalContext] = useState<any>(null);
  const [fundContext, setFundContext] = useState<any>(null);
  const [recommendation, setRecommendation] = useState<FundResearchRecommendation | null>(null);
  const [batchJob, setBatchJob] = useState<FundResearchBatchJob | null>(null);
  const [batchJobId, setBatchJobId] = useState<number | null>(null);
  const [dcaPlans, setDcaPlans] = useState<FundDCAPlan[]>([]);
  const [dcaRuns, setDcaRuns] = useState<FundDCARun[]>([]);

  const [universeFunds, setUniverseFunds] = useState<FundUniverseItem[]>([]);
  const [universeCount, setUniverseCount] = useState(0);
  const [universeLastUpdated, setUniverseLastUpdated] = useState<string | null>(null);
  const [syncCode, setSyncCode] = useState('');
  const [fundPositions, setFundPositions] = useState<UnifiedPosition[]>([]);

  const [loadingSelection, setLoadingSelection] = useState(false);
  const [loadingBatch, setLoadingBatch] = useState(false);
  const [loadingSingle, setLoadingSingle] = useState(false);
  const [loadingContext, setLoadingContext] = useState(false);
  const [loadingPlans, setLoadingPlans] = useState(false);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [loadingUniverse, setLoadingUniverse] = useState(false);
  const [loadingUniverseSync, setLoadingUniverseSync] = useState(false);
  const [loadingPositions, setLoadingPositions] = useState(false);

  const [message, setMessage] = useState<{
    severity: 'success' | 'info' | 'warning' | 'error';
    text: string;
  } | null>(null);

  const selectedCodes = useMemo(
    () => (selection?.selected || []).map((item) => item.code).filter(Boolean),
    [selection],
  );

  const batchProgress = useMemo(() => {
    const ratio = batchJob?.progress?.done_ratio || 0;
    return Math.round(ratio * 100);
  }, [batchJob]);

  const setTabWithQuery = (next: number) => {
    setTab(next);
    const key = TAB_KEYS[next] || TAB_KEYS[0];
    const params = new URLSearchParams(searchParams);
    params.set('tab', key);
    setSearchParams(params, { replace: true });
  };

  const switchTab = (key: TabKey) => {
    const idx = TAB_KEYS.indexOf(key);
    setTabWithQuery(idx >= 0 ? idx : 0);
  };

  const loadGlobalContext = async () => {
    setLoadingContext(true);
    try {
      const [ctx, suggest] = await Promise.all([
        fetchFundResearchGlobalContext(),
        fetchFundConstraintSuggestions(),
      ]);
      setGlobalContext(ctx);
      setConstraintSuggestion(suggest);
      if (!maxSingleDay.trim() && suggest?.final_suggestion?.max_single_day_amount !== undefined) {
        setMaxSingleDay(String(suggest.final_suggestion.max_single_day_amount));
      }
      if (suggest?.final_suggestion?.max_drawdown_tolerance !== undefined) {
        setMaxDrawdown(String(suggest.final_suggestion.max_drawdown_tolerance));
      }
      if (suggest?.final_suggestion?.tactical_boost !== undefined) {
        setTacticalBoost(Boolean(suggest.final_suggestion.tactical_boost));
      }
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || '加载全局上下文失败' });
    } finally {
      setLoadingContext(false);
    }
  };

  const loadUniverse = async () => {
    setLoadingUniverse(true);
    try {
      const data = await fetchFundResearchUniverse(true, 300);
      setUniverseFunds(data.items || []);
      setUniverseCount(data.count || 0);
      setUniverseLastUpdated(data.last_updated || null);
    } catch (error: any) {
      setMessage({ severity: 'warning', text: error?.message || '加载基金池失败' });
    } finally {
      setLoadingUniverse(false);
    }
  };

  const syncUniverse = async (fullSync: boolean) => {
    if (!fullSync && !syncCode.trim() && !singleCode.trim()) {
      setMessage({ severity: 'warning', text: '请先输入基金代码，再做增量同步' });
      return;
    }
    setLoadingUniverseSync(true);
    try {
      const code = (syncCode || singleCode).trim();
      const codes = fullSync ? undefined : [code];
      const result = await syncFundResearchUniverse(fullSync, codes);
      setMessage({
        severity: 'success',
        text: fullSync
          ? `候选池全量同步完成，当前共 ${result.universe_count} 只`
          : `候选池增量同步完成：${code}`,
      });
      await loadUniverse();
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || '候选池同步失败' });
    } finally {
      setLoadingUniverseSync(false);
    }
  };

  const loadFundPositions = async () => {
    setLoadingPositions(true);
    try {
      const portfolio = await fetchDefaultPortfolio();
      if (!portfolio?.id) {
        setFundPositions([]);
        return;
      }
      const summary = await fetchPortfolioSummaryNew(portfolio.id);
      setFundPositions((summary.positions || []).filter((p) => p.asset_type === 'fund'));
    } catch (error: any) {
      setMessage({ severity: 'warning', text: error?.message || '加载组合持仓失败' });
    } finally {
      setLoadingPositions(false);
    }
  };

  const loadDCAPlans = async () => {
    setLoadingPlans(true);
    try {
      const data = await fetchFundDCAPlans({ limit: 300 });
      setDcaPlans(data.plans || []);
    } catch (error: any) {
      setMessage({ severity: 'warning', text: error?.message || '加载定投计划失败' });
    } finally {
      setLoadingPlans(false);
    }
  };

  const loadDCARuns = async () => {
    setLoadingRuns(true);
    try {
      const data = await fetchFundDCARuns({ limit: 60 });
      setDcaRuns(data.runs || []);
    } catch (error: any) {
      setMessage({ severity: 'warning', text: error?.message || '加载定投记录失败' });
    } finally {
      setLoadingRuns(false);
    }
  };

  useEffect(() => {
    const next = tabIndexFromKey(searchParams.get('tab'));
    setTab((prev) => (prev === next ? prev : next));
  }, [searchParams]);

  useEffect(() => {
    void loadGlobalContext();
    void loadUniverse();
    void loadFundPositions();
    void loadDCAPlans();
    void loadDCARuns();
  }, []);

  useEffect(() => {
    if (!batchJobId) return;
    let stopped = false;

    const poll = async () => {
      try {
        const data = await fetchFundResearchBatchJob(batchJobId);
        if (stopped) return;
        setBatchJob(data);
        if (FINAL_JOB_STATUS.has(String(data.status || '').toLowerCase())) {
          setBatchJobId(null);
          void loadGlobalContext();
          void loadDCARuns();
        }
      } catch {
        // 静默轮询错误
      }
    };

    void poll();
    const timer = window.setInterval(poll, 2500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [batchJobId]);

  const runSelection = async () => {
    const parsedTopN = parseNumber(topN);
    const parsedCandidateLimit = parseNumber(candidateLimit);
    if (!parsedTopN || parsedTopN < 1) {
      setMessage({ severity: 'warning', text: 'TopN 输入无效' });
      return;
    }
    if (!parsedCandidateLimit || parsedCandidateLimit < parsedTopN) {
      setMessage({ severity: 'warning', text: '候选数需大于等于 TopN' });
      return;
    }
    if (universeCount <= 0) {
      setMessage({ severity: 'warning', text: '候选池为空，请先执行“全量同步候选池”' });
      return;
    }

    setLoadingSelection(true);
    try {
      const data = await runFundAISelection({
        top_n: Math.round(parsedTopN),
        candidate_limit: Math.round(parsedCandidateLimit),
        refresh_missing: true,
        analysis_mode: analysisMode,
      });
      setSelection(data);
      if (data.selected?.[0]?.code) {
        setSingleCode(data.selected[0].code);
      }
      if ((data.selected_count || 0) <= 0 || (data.candidate_count || 0) <= 0) {
        setMessage({
          severity: 'warning',
          text: 'AI 精选无结果：候选池为空或未通过硬过滤，请先同步候选池并检查筛选条件',
        });
      } else {
        setMessage({
          severity: 'success',
          text: `AI 精选完成：候选 ${data.candidate_count} 只，入选 ${data.selected_count} 只`,
        });
      }
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || 'AI 精选失败' });
    } finally {
      setLoadingSelection(false);
    }
  };

  const runBatchResearch = async () => {
    const parsedBase = parseNumber(baseAmount);
    if (!parsedBase || parsedBase <= 0) {
      setMessage({ severity: 'warning', text: '基础金额输入无效' });
      return;
    }
    if (!selectedCodes.length) {
      setMessage({ severity: 'warning', text: '请先运行 AI 精选' });
      return;
    }

    setLoadingBatch(true);
    try {
      const data = await createFundResearchBatchRecommendJob({
        codes: selectedCodes,
        top_n: selectedCodes.length,
        source: 'ai_select',
        base_amount: parsedBase,
        max_single_day_amount: parseNumber(maxSingleDay),
        max_drawdown_tolerance: parseNumber(maxDrawdown),
        tactical_boost: tacticalBoost,
        strict_tactical: tacticalBoost,
        analysis_mode: analysisMode,
        use_global_cash: true,
        use_auto_dca: true,
        refresh_missing: true,
        auto_start: true,
        max_workers: analysisMode === 'deep' ? 2 : 4,
      });
      setBatchJob(data.job || null);
      setBatchJobId(data.job_id);
      setMessage({ severity: 'success', text: `已启动一键研究：${data.count} 只` });
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || '一键研究失败' });
    } finally {
      setLoadingBatch(false);
    }
  };

  const runSingleDecision = async () => {
    const code = singleCode.trim();
    const parsedBase = parseNumber(baseAmount);
    if (!code) {
      setMessage({ severity: 'warning', text: '请先输入基金代码' });
      return;
    }
    if (!parsedBase || parsedBase <= 0) {
      setMessage({ severity: 'warning', text: '基础金额输入无效' });
      return;
    }

    setLoadingSingle(true);
    try {
      const result = await recommendFundResearch({
        code,
        base_amount: parsedBase,
        max_single_day_amount: parseNumber(maxSingleDay),
        max_drawdown_tolerance: parseNumber(maxDrawdown),
        tactical_boost: tacticalBoost,
        strict_tactical: tacticalBoost,
        analysis_mode: analysisMode,
        use_global_cash: true,
        use_auto_dca: true,
        refresh_missing: true,
      });
      setRecommendation(result);
      const ctx = await fetchFundResearchFundContext(code);
      setFundContext(ctx);
      setMessage({ severity: 'success', text: `单只决策完成：${code}` });
      await Promise.all([loadGlobalContext(), loadDCARuns()]);
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || '单只决策失败' });
    } finally {
      setLoadingSingle(false);
    }
  };

  const createPlan = async () => {
    const code = newPlanCode.trim();
    const amount = parseNumber(newPlanAmount);
    if (!code) {
      setMessage({ severity: 'warning', text: '请输入定投基金代码' });
      return;
    }
    if (!amount || amount <= 0) {
      setMessage({ severity: 'warning', text: '请输入有效定投金额' });
      return;
    }

    try {
      await createFundDCAPlan({
        code,
        amount_per_cycle: amount,
        frequency: newPlanFreq,
      });
      setNewPlanCode('');
      setMessage({ severity: 'success', text: '定投计划创建成功' });
      await Promise.all([loadDCAPlans(), loadGlobalContext()]);
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || '定投计划创建失败' });
    }
  };

  const updatePlanAction = async (planId: number, action: 'pause' | 'resume' | 'stop') => {
    try {
      await updateFundDCAPlan(planId, { action });
      const actionText = action === 'pause' ? '暂停' : action === 'resume' ? '恢复' : '停止';
      setMessage({ severity: 'info', text: `计划已${actionText}` });
      await Promise.all([loadDCAPlans(), loadGlobalContext()]);
    } catch (error: any) {
      setMessage({ severity: 'warning', text: error?.message || '计划更新失败' });
    }
  };

  const runDcaSimulation = async () => {
    try {
      const result = await simulateFundDCA({ max_plans: 200 });
      setMessage({ severity: 'success', text: `已模拟定投：${result.simulated_count}/${result.due_count}` });
      await Promise.all([loadDCARuns(), loadDCAPlans(), loadGlobalContext()]);
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || '定投模拟失败' });
    }
  };

  const jumpToDecision = (code: string) => {
    setSingleCode(code);
    switchTab('decision');
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.2 }}>
      <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', p: 2.2 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 800 }}>基金工作台</Typography>
            <Typography variant="body2" color="text.secondary">
              基金池、AI 精选、研究决策、交易与定投统一到一个页面，避免重复操作。
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Chip label={`可用现金：${globalContext?.context?.available_cash ?? '-'}`} color="primary" variant="outlined" />
            <Chip label={`今日计划定投：${globalContext?.context?.planned_dca_today ?? 0}`} variant="outlined" />
            <Chip label={`活跃定投计划：${globalContext?.context?.active_dca_plan_count ?? 0}`} variant="outlined" />
          </Stack>
        </Stack>

        <Divider sx={{ my: 1.5 }} />

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} flexWrap="wrap">
          <TextField
            select
            size="small"
            label="分析深度"
            value={analysisMode}
            onChange={(e) => setAnalysisMode(e.target.value as 'quick' | 'deep')}
            sx={{ minWidth: 120 }}
          >
            <MenuItem value="quick">快速</MenuItem>
            <MenuItem value="deep">深度辩论</MenuItem>
          </TextField>
          <TextField size="small" label="TopN" value={topN} onChange={(e) => setTopN(e.target.value)} sx={{ width: 100 }} />
          <TextField size="small" label="候选数" value={candidateLimit} onChange={(e) => setCandidateLimit(e.target.value)} sx={{ width: 110 }} />
          <TextField size="small" label="基础金额" value={baseAmount} onChange={(e) => setBaseAmount(e.target.value)} sx={{ width: 120 }} />
          <TextField size="small" label="单日上限" value={maxSingleDay} onChange={(e) => setMaxSingleDay(e.target.value)} sx={{ width: 120 }} />
          <TextField size="small" label="回撤容忍(%)" value={maxDrawdown} onChange={(e) => setMaxDrawdown(e.target.value)} sx={{ width: 130 }} />
          <FormControlLabel control={<Switch checked={tacticalBoost} onChange={(_, v) => setTacticalBoost(v)} />} label="波段增强" />
          <Button variant="outlined" onClick={() => { void loadGlobalContext(); void loadUniverse(); void loadFundPositions(); }} startIcon={loadingContext ? <CircularProgress size={14} /> : <RefreshIcon />}>
            刷新全局数据
          </Button>
        </Stack>
      </Paper>

      {message && (
        <Alert severity={message.severity} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}

      <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', overflow: 'hidden' }}>
        <Tabs value={tab} onChange={(_, v) => setTabWithQuery(v)}>
          <Tab icon={<FolderIcon />} iconPosition="start" label="基金池" />
          <Tab icon={<AutoAwesomeIcon />} iconPosition="start" label="AI 精选" />
          <Tab icon={<PsychologyAltIcon />} iconPosition="start" label="研究决策" />
          <Tab icon={<AccountBalanceWalletIcon />} iconPosition="start" label="交易与定投" />
        </Tabs>
        <Divider />

        {tab === 0 && (
          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Stack
                direction={{ xs: 'column', md: 'row' }}
                justifyContent="space-between"
                spacing={1}
                sx={{ mb: 1 }}
              >
                <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                  候选基金池（研究专用）
                </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap">
                  <Chip size="small" variant="outlined" label={`候选总数：${universeCount}`} />
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`更新时间：${universeLastUpdated || '-'}`}
                  />
                </Stack>
              </Stack>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ mb: 1.2 }}>
                <TextField
                  size="small"
                  label="增量同步代码"
                  value={syncCode}
                  onChange={(e) => setSyncCode(e.target.value)}
                  sx={{ minWidth: 150 }}
                />
                <Button
                  variant="outlined"
                  onClick={() => void syncUniverse(true)}
                  disabled={loadingUniverseSync}
                  startIcon={loadingUniverseSync ? <CircularProgress size={14} /> : <RefreshIcon />}
                >
                  全量同步候选池
                </Button>
                <Button
                  variant="outlined"
                  onClick={() => void syncUniverse(false)}
                  disabled={loadingUniverseSync}
                >
                  按代码增量同步
                </Button>
              </Stack>
              {loadingUniverse ? (
                <CircularProgress size={20} />
              ) : universeFunds.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  候选池为空，请先点击“全量同步候选池”初始化后再运行 AI 精选。
                </Typography>
              ) : (
                <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>代码</TableCell>
                        <TableCell>名称</TableCell>
                        <TableCell>类型</TableCell>
                        <TableCell>可定投</TableCell>
                        <TableCell>操作</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {universeFunds.slice(0, 50).map((fund) => (
                        <TableRow key={fund.code} hover>
                          <TableCell>{fund.code}</TableCell>
                          <TableCell>{fund.name}</TableCell>
                          <TableCell>{fund.fund_type || '-'}</TableCell>
                          <TableCell>{fund.is_dca_eligible ? '是' : '否'}</TableCell>
                          <TableCell>
                            <Button size="small" onClick={() => jumpToDecision(fund.code)}>研究</Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Paper>

            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 1 }}>我的组合-基金持仓</Typography>
              {loadingPositions ? (
                <CircularProgress size={20} />
              ) : fundPositions.length === 0 ? (
                <Typography variant="body2" color="text.secondary">默认组合中暂无基金持仓</Typography>
              ) : (
                <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>基金</TableCell>
                        <TableCell>份额</TableCell>
                        <TableCell>均价</TableCell>
                        <TableCell>市值</TableCell>
                        <TableCell>操作</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {fundPositions.map((position) => (
                        <TableRow key={position.id} hover>
                          <TableCell>{position.asset_code} {position.asset_name || ''}</TableCell>
                          <TableCell>{position.total_shares}</TableCell>
                          <TableCell>{position.average_cost}</TableCell>
                          <TableCell>{position.current_value ?? '-'}</TableCell>
                          <TableCell>
                            <Button size="small" onClick={() => jumpToDecision(position.asset_code)}>研究该持仓</Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Paper>
          </Box>
        )}

        {tab === 1 && (
          <Box sx={{ p: 2 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ mb: 1.5 }}>
              <Button
                variant="contained"
                startIcon={loadingSelection ? <CircularProgress size={14} color="inherit" /> : <AutoAwesomeIcon />}
                onClick={runSelection}
                disabled={loadingSelection}
              >
                运行 AI 精选
              </Button>
              <Button
                variant="outlined"
                startIcon={loadingBatch ? <CircularProgress size={14} /> : <PlayArrowIcon />}
                onClick={runBatchResearch}
                disabled={loadingBatch || !selectedCodes.length}
              >
                一键研究精选结果
              </Button>
              <Button variant="text" onClick={() => switchTab('decision')}>切到研究决策</Button>
            </Stack>

            {!selection ? (
              <Typography variant="body2" color="text.secondary">还没有精选结果，点击“运行 AI 精选”开始。</Typography>
            ) : selection.selected_count <= 0 ? (
              <Alert severity="warning" sx={{ mb: 1 }}>
                当前无可用精选结果。请先在“基金池”页完成候选池同步，再重新运行 AI 精选。
              </Alert>
            ) : (
              <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px', mb: 1.5 }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>排名</TableCell>
                      <TableCell>基金</TableCell>
                      <TableCell>总分</TableCell>
                      <TableCell>近1月</TableCell>
                      <TableCell>近3月</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {selection.selected.map((row) => (
                      <TableRow key={row.code} hover sx={{ cursor: 'pointer' }} onClick={() => jumpToDecision(row.code)}>
                        <TableCell>{row.rank}</TableCell>
                        <TableCell>{row.code} {row.name}</TableCell>
                        <TableCell>{row.score?.toFixed?.(2) ?? row.score}</TableCell>
                        <TableCell>{row.return_1m ?? '-'}</TableCell>
                        <TableCell>{row.return_3m ?? '-'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}

            {selection && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                本轮候选 {selection.candidate_count} 只 ｜ 入选 {selection.selected_count} 只
              </Typography>
            )}

            {batchJob && (
              <Typography variant="body2" color="text.secondary">
                批量任务状态 {batchJob.status} ｜ 进度 {batchProgress}% ｜ 完成 {batchJob.completed_count}/{batchJob.total_count}
              </Typography>
            )}
          </Box>
        )}

        {tab === 2 && (
          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1.6 }}>
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 1 }}>单只基金决策</Typography>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={1}>
                <TextField size="small" label="基金代码" value={singleCode} onChange={(e) => setSingleCode(e.target.value)} sx={{ minWidth: 180 }} />
                <Button
                  variant="contained"
                  startIcon={loadingSingle ? <CircularProgress size={14} color="inherit" /> : <PsychologyAltIcon />}
                  onClick={runSingleDecision}
                  disabled={loadingSingle}
                >
                  运行决策
                </Button>
              </Stack>

              {fundContext?.context?.fund_context && (
                <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap">
                  <Chip label={`近30天日均定投：${fundContext.context.fund_context.existing_dca_daily_amount ?? '-'}`} />
                  <Chip label={`今日计划定投：${fundContext.context.fund_context.planned_dca_today ?? 0}`} />
                  <Chip label={`活跃计划数：${fundContext.context.fund_context.active_dca_plan_count ?? 0}`} />
                </Stack>
              )}
            </Paper>

            {recommendation && (
              <Paper variant="outlined" sx={{ p: 1.5 }}>
                <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" sx={{ mb: 0.8 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                    {recommendation.name}（{recommendation.code}）
                  </Typography>
                  <Stack direction="row" spacing={1}>
                    <Chip color="primary" label={`动作：${actionToText(recommendation.action)}`} />
                    <Chip label={`建议金额：${recommendation.suggested_amount}`} />
                    <Chip label={`置信度：${(recommendation.confidence * 100).toFixed(0)}%`} />
                  </Stack>
                </Stack>
                <Typography variant="body2" color="text.secondary">{recommendation.strategy_explanation}</Typography>
              </Paper>
            )}
          </Box>
        )}

        {tab === 3 && (
          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1.6 }}>
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1}>
                <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>交易与定投</Typography>
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1}>
                  <Button variant="outlined" onClick={runDcaSimulation}>模拟今日定投</Button>
                  <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => { void loadDCAPlans(); void loadDCARuns(); }}>
                    刷新定投数据
                  </Button>
                </Stack>
              </Stack>
            </Paper>

            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 1 }}>定投计划（自动联动决策）</Typography>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ mb: 1 }}>
                <TextField size="small" label="基金代码" value={newPlanCode} onChange={(e) => setNewPlanCode(e.target.value)} sx={{ minWidth: 140 }} />
                <TextField size="small" label="每期金额" value={newPlanAmount} onChange={(e) => setNewPlanAmount(e.target.value)} sx={{ minWidth: 120 }} />
                <TextField
                  select
                  size="small"
                  label="频率"
                  value={newPlanFreq}
                  onChange={(e) => setNewPlanFreq(e.target.value as 'daily' | 'weekly' | 'monthly')}
                  sx={{ minWidth: 120 }}
                >
                  <MenuItem value="daily">每日</MenuItem>
                  <MenuItem value="weekly">每周</MenuItem>
                  <MenuItem value="monthly">每月</MenuItem>
                </TextField>
                <Button variant="contained" startIcon={<SavingsIcon />} onClick={createPlan}>新增计划</Button>
              </Stack>

              {loadingPlans ? (
                <CircularProgress size={20} />
              ) : dcaPlans.length === 0 ? (
                <Typography variant="body2" color="text.secondary">暂无定投计划</Typography>
              ) : (
                <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>基金</TableCell>
                        <TableCell>金额</TableCell>
                        <TableCell>频率</TableCell>
                        <TableCell>下次日期</TableCell>
                        <TableCell>状态</TableCell>
                        <TableCell>操作</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {dcaPlans.map((plan) => (
                        <TableRow key={plan.id}>
                          <TableCell>{plan.fund_code} {plan.fund_name || ''}</TableCell>
                          <TableCell>{plan.amount_per_cycle}</TableCell>
                          <TableCell>{plan.frequency}</TableCell>
                          <TableCell>{plan.next_run_date}</TableCell>
                          <TableCell>{plan.status}</TableCell>
                          <TableCell>
                            <Stack direction="row" spacing={0.5}>
                              {plan.status === 'active' && (
                                <Button size="small" onClick={() => updatePlanAction(plan.id, 'pause')}>暂停</Button>
                              )}
                              {plan.status === 'paused' && (
                                <Button size="small" onClick={() => updatePlanAction(plan.id, 'resume')}>恢复</Button>
                              )}
                              {plan.status !== 'stopped' && (
                                <Button size="small" color="warning" onClick={() => updatePlanAction(plan.id, 'stop')}>停止</Button>
                              )}
                            </Stack>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Paper>

            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 1 }}>定投运行记录（最近 60 条）</Typography>
              {loadingRuns ? (
                <CircularProgress size={20} />
              ) : dcaRuns.length === 0 ? (
                <Typography variant="body2" color="text.secondary">暂无运行记录</Typography>
              ) : (
                <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>日期</TableCell>
                        <TableCell>基金</TableCell>
                        <TableCell>计划金额</TableCell>
                        <TableCell>建议金额</TableCell>
                        <TableCell>状态</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {dcaRuns.map((run) => (
                        <TableRow key={run.id}>
                          <TableCell>{run.scheduled_date}</TableCell>
                          <TableCell>{run.fund_code}</TableCell>
                          <TableCell>{run.planned_amount}</TableCell>
                          <TableCell>{run.suggested_amount ?? '-'}</TableCell>
                          <TableCell>{run.status}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Paper>
          </Box>
        )}
      </Paper>
    </Box>
  );
}
