import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
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
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import SyncIcon from '@mui/icons-material/Sync';
import RefreshIcon from '@mui/icons-material/Refresh';
import ScienceIcon from '@mui/icons-material/Science';

import type {
  FundItem,
  FundResearchRecommendation,
  FundResearchScore,
  FundUniverseItem,
  RecommendationFundV2,
} from '../../api';
import {
  fetchFundResearchReport,
  fetchFundResearchCases,
  fetchFundResearchReviewSummary,
  fetchFundResearchUniverse,
  getLongTermFundsV2,
  recommendFundResearch,
  scoreFundResearch,
  submitFundResearchReview,
  syncFundResearchUniverse,
} from '../../api';

interface FundResearchWorkbenchProps {
  trackedFunds: FundItem[];
}

interface CacheState {
  ttl_seconds: number;
  age_seconds?: number;
  stale?: boolean;
  refreshing?: boolean;
}

type ReviewSummaryData = Awaited<ReturnType<typeof fetchFundResearchReviewSummary>>;
type CaseLibraryData = Awaited<ReturnType<typeof fetchFundResearchCases>>;
type CaseLibraryItem = CaseLibraryData['cases'][number];

const parseNumberInput = (raw: string): number | undefined => {
  if (!raw.trim()) return undefined;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) return undefined;
  return value;
};

const parseSignedNumberInput = (raw: string): number | undefined => {
  if (!raw.trim()) return undefined;
  const value = Number(raw);
  if (!Number.isFinite(value)) return undefined;
  return value;
};

const actionChipColor = (action?: string): 'success' | 'warning' | 'error' | 'default' => {
  if (action === 'add') return 'success';
  if (action === 'hold') return 'warning';
  if (action === 'pause') return 'error';
  return 'default';
};

export default function FundResearchWorkbench({ trackedFunds }: FundResearchWorkbenchProps) {
  const { t } = useTranslation();

  const [fundCode, setFundCode] = useState('');
  const [baseAmount, setBaseAmount] = useState('30');
  const [availableCash, setAvailableCash] = useState('');
  const [maxSingleDayAmount, setMaxSingleDayAmount] = useState('');
  const [existingDcaDailyAmount, setExistingDcaDailyAmount] = useState('');
  const [maxDrawdownTolerance, setMaxDrawdownTolerance] = useState('35');
  const [tacticalBoost, setTacticalBoost] = useState(true);

  const [loadingUniverse, setLoadingUniverse] = useState(false);
  const [loadingScore, setLoadingScore] = useState(false);
  const [loadingRecommend, setLoadingRecommend] = useState(false);
  const [loadingReport, setLoadingReport] = useState(false);
  const [loadingAiPicks, setLoadingAiPicks] = useState(false);
  const [loadingReviewSubmit, setLoadingReviewSubmit] = useState(false);
  const [loadingReviewSummary, setLoadingReviewSummary] = useState(false);
  const [loadingCases, setLoadingCases] = useState(false);
  const [message, setMessage] = useState<{ severity: 'success' | 'info' | 'warning' | 'error'; text: string } | null>(null);

  const [universeCount, setUniverseCount] = useState(0);
  const [universeLastUpdated, setUniverseLastUpdated] = useState<string | null>(null);
  const [universePreview, setUniversePreview] = useState<FundUniverseItem[]>([]);
  const [scores, setScores] = useState<FundResearchScore[]>([]);
  const [recommendation, setRecommendation] = useState<FundResearchRecommendation | null>(null);
  const [cacheState, setCacheState] = useState<CacheState | null>(null);
  const [aiPicks, setAiPicks] = useState<RecommendationFundV2[]>([]);
  const [reviewSummary, setReviewSummary] = useState<ReviewSummaryData | null>(null);
  const [caseLibrary, setCaseLibrary] = useState<CaseLibraryItem[]>([]);

  const [reviewActualReturn, setReviewActualReturn] = useState('');
  const [reviewMaxDrawdown, setReviewMaxDrawdown] = useState('');
  const [reviewExecutedAmount, setReviewExecutedAmount] = useState('');
  const [reviewFollowedPlan, setReviewFollowedPlan] = useState(true);
  const [reviewMarketState, setReviewMarketState] = useState('sideways');
  const [reviewStrategyVersion, setReviewStrategyVersion] = useState('p1');
  const [reviewReflection, setReviewReflection] = useState('');

  const [summaryWindow, setSummaryWindow] = useState('20');
  const [caseOutcomeFilter, setCaseOutcomeFilter] = useState('');
  const [caseMarketFilter, setCaseMarketFilter] = useState('');
  const [caseStrategyFilter, setCaseStrategyFilter] = useState('');

  const quickCodes = useMemo(() => trackedFunds.slice(0, 10), [trackedFunds]);

  const loadUniverse = async () => {
    setLoadingUniverse(true);
    try {
      const data = await fetchFundResearchUniverse(true, 50);
      setUniverseCount(data.count || 0);
      setUniverseLastUpdated(data.last_updated || null);
      setUniversePreview(data.items || []);
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.load_universe_failed') });
    } finally {
      setLoadingUniverse(false);
    }
  };

  useEffect(() => {
    void loadUniverse();
  }, []);

  useEffect(() => {
    if (!fundCode && trackedFunds.length > 0) {
      setFundCode(trackedFunds[0].code);
    }
  }, [trackedFunds, fundCode]);

  const getConfidenceBandLabel = (band?: string) => {
    if (band === 'high') return t('funds.research.confidence_high');
    if (band === 'medium') return t('funds.research.confidence_medium');
    return t('funds.research.confidence_low');
  };

  const runSync = async (fullSync: boolean) => {
    setLoadingUniverse(true);
    try {
      const codes = !fullSync && fundCode ? [fundCode] : undefined;
      const result = await syncFundResearchUniverse(fullSync, codes);
      setMessage({
        severity: 'success',
        text: `${t('funds.research.sync_success')} ${result.updated}`,
      });
      await loadUniverse();
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.sync_failed') });
    } finally {
      setLoadingUniverse(false);
    }
  };

  const runScore = async () => {
    setLoadingScore(true);
    try {
      const result = await scoreFundResearch({
        codes: fundCode ? [fundCode] : undefined,
        top_n: 20,
        min_score: 0,
        refresh_missing: true,
      });
      setScores(result.scores || []);
      setMessage({
        severity: 'info',
        text: `${t('funds.research.score_done')}: ${result.eligible_count}/${result.universe_size}`,
      });
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.score_failed') });
    } finally {
      setLoadingScore(false);
    }
  };

  const loadAiPicks = async () => {
    setLoadingAiPicks(true);
    try {
      const result = await getLongTermFundsV2(10);
      const picks = (result.recommendations || result.funds || []) as RecommendationFundV2[];
      setAiPicks(picks.slice(0, 10));
      if (!picks.length) {
        setMessage({ severity: 'info', text: t('funds.research.ai_pick_empty') });
      }
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.ai_pick_failed') });
    } finally {
      setLoadingAiPicks(false);
    }
  };

  const loadReviewSummary = async () => {
    setLoadingReviewSummary(true);
    try {
      const parsedWindow = parseNumberInput(summaryWindow);
      const data = await fetchFundResearchReviewSummary(
        fundCode.trim() || undefined,
        parsedWindow ? Math.max(5, Math.round(parsedWindow)) : 20,
      );
      setReviewSummary(data);
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.load_review_failed') });
    } finally {
      setLoadingReviewSummary(false);
    }
  };

  const loadCaseLibrary = async () => {
    setLoadingCases(true);
    try {
      const data = await fetchFundResearchCases({
        code: fundCode.trim() || undefined,
        outcome: caseOutcomeFilter || undefined,
        market_state: caseMarketFilter || undefined,
        strategy_version: caseStrategyFilter || undefined,
        limit: 50,
      });
      setCaseLibrary(data.cases || []);
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.load_cases_failed') });
    } finally {
      setLoadingCases(false);
    }
  };

  const submitReview = async () => {
    if (!fundCode.trim()) {
      setMessage({ severity: 'warning', text: t('funds.research.code_required') });
      return;
    }
    const actualReturn = parseSignedNumberInput(reviewActualReturn);
    if (actualReturn === undefined) {
      setMessage({ severity: 'warning', text: t('funds.research.review_actual_return_invalid') });
      return;
    }
    const maxDrawdown = parseNumberInput(reviewMaxDrawdown);
    if (maxDrawdown === undefined) {
      setMessage({ severity: 'warning', text: t('funds.research.review_max_drawdown_invalid') });
      return;
    }

    setLoadingReviewSubmit(true);
    try {
      const result = await submitFundResearchReview({
        code: fundCode,
        decision_id: recommendation?.decision_id,
        actual_return_pct: actualReturn,
        max_drawdown_pct: maxDrawdown,
        executed_amount: parseNumberInput(reviewExecutedAmount),
        followed_plan: reviewFollowedPlan,
        market_state: reviewMarketState || undefined,
        reflection: reviewReflection.trim() || undefined,
        strategy_version: reviewStrategyVersion.trim() || 'p1',
      });
      setMessage({
        severity: 'success',
        text: `${t('funds.research.submit_review_success')}: ${result.outcome}`,
      });
      await Promise.all([loadReviewSummary(), loadCaseLibrary()]);
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.submit_review_failed') });
    } finally {
      setLoadingReviewSubmit(false);
    }
  };

  const runRecommend = async () => {
    if (!fundCode.trim()) {
      setMessage({ severity: 'warning', text: t('funds.research.code_required') });
      return;
    }
    const baseAmountValue = parseNumberInput(baseAmount);
    if (baseAmountValue === undefined) {
      setMessage({ severity: 'warning', text: t('funds.research.base_amount_invalid') });
      return;
    }

    setLoadingRecommend(true);
    try {
      const data = await recommendFundResearch({
        code: fundCode,
        base_amount: baseAmountValue,
        available_cash: parseNumberInput(availableCash),
        max_single_day_amount: parseNumberInput(maxSingleDayAmount),
        existing_dca_daily_amount: parseNumberInput(existingDcaDailyAmount),
        max_drawdown_tolerance: parseNumberInput(maxDrawdownTolerance),
        tactical_boost: tacticalBoost,
        strict_tactical: tacticalBoost,
        refresh_missing: true,
      });
      setRecommendation(data);
      setMessage({ severity: 'success', text: t('funds.research.recommend_done') });
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.recommend_failed') });
    } finally {
      setLoadingRecommend(false);
    }
  };

  const loadReport = async (refresh: boolean) => {
    if (!fundCode.trim()) {
      setMessage({ severity: 'warning', text: t('funds.research.code_required') });
      return;
    }
    setLoadingReport(true);
    try {
      const data = await fetchFundResearchReport(fundCode, refresh);
      setCacheState(data.cache || null);
      if (data.available && data.report) {
        setRecommendation(data.report);
        setMessage({
          severity: 'info',
          text: refresh ? t('funds.research.report_refreshed') : t('funds.research.report_loaded'),
        });
      } else {
        setMessage({ severity: 'warning', text: data.message || t('funds.research.report_empty') });
      }
    } catch (error: any) {
      setMessage({ severity: 'error', text: error?.message || t('funds.research.report_failed') });
    } finally {
      setLoadingReport(false);
    }
  };

  useEffect(() => {
    if (!fundCode.trim()) return;
    void loadReviewSummary();
    void loadCaseLibrary();
  }, [fundCode]);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
      <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between">
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 800 }}>
              {t('funds.research.title')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t('funds.research.subtitle')}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Chip label={`${t('funds.research.pool_count')}: ${universeCount}`} color="primary" variant="outlined" />
            {universeLastUpdated && (
              <Chip label={`${t('funds.research.updated')}: ${universeLastUpdated}`} variant="outlined" />
            )}
          </Stack>
        </Stack>

        <Divider sx={{ my: 2 }} />

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} sx={{ mb: 1.5 }}>
          <TextField
            label={t('funds.research.fund_code')}
            value={fundCode}
            onChange={(e) => setFundCode(e.target.value)}
            size="small"
            sx={{ minWidth: 180 }}
          />
          <TextField
            label={t('funds.research.base_amount')}
            value={baseAmount}
            onChange={(e) => setBaseAmount(e.target.value)}
            size="small"
            sx={{ minWidth: 140 }}
          />
          <TextField
            label={t('funds.research.available_cash')}
            value={availableCash}
            onChange={(e) => setAvailableCash(e.target.value)}
            size="small"
            sx={{ minWidth: 140 }}
          />
          <TextField
            label={t('funds.research.max_single_day')}
            value={maxSingleDayAmount}
            onChange={(e) => setMaxSingleDayAmount(e.target.value)}
            size="small"
            sx={{ minWidth: 140 }}
          />
          <TextField
            label={t('funds.research.existing_dca')}
            value={existingDcaDailyAmount}
            onChange={(e) => setExistingDcaDailyAmount(e.target.value)}
            size="small"
            sx={{ minWidth: 140 }}
          />
          <TextField
            label={t('funds.research.max_drawdown_tolerance')}
            value={maxDrawdownTolerance}
            onChange={(e) => setMaxDrawdownTolerance(e.target.value)}
            size="small"
            sx={{ minWidth: 140 }}
          />
          <FormControlLabel
            control={<Switch checked={tacticalBoost} onChange={(_, checked) => setTacticalBoost(checked)} />}
            label={t('funds.research.strict_tactical')}
            sx={{ ml: { md: 0.5 } }}
          />
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
          {t('funds.research.tactical_help')}
        </Typography>

        {quickCodes.length > 0 && (
          <Stack direction="row" spacing={1} sx={{ mb: 1.5 }} flexWrap="wrap">
            {quickCodes.map((fund) => (
              <Chip
                key={fund.code}
                label={`${fund.code} ${fund.name}`}
                clickable
                color={fund.code === fundCode ? 'primary' : 'default'}
                onClick={() => setFundCode(fund.code)}
                sx={{ mb: 0.8 }}
              />
            ))}
          </Stack>
        )}

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1}>
          <Button
            variant="outlined"
            startIcon={loadingUniverse ? <CircularProgress size={14} /> : <SyncIcon />}
            onClick={() => runSync(false)}
            disabled={loadingUniverse}
          >
            {t('funds.research.sync_incremental')}
          </Button>
          <Button
            variant="outlined"
            startIcon={loadingUniverse ? <CircularProgress size={14} /> : <RefreshIcon />}
            onClick={() => runSync(true)}
            disabled={loadingUniverse}
          >
            {t('funds.research.sync_full')}
          </Button>
          <Button
            variant="outlined"
            startIcon={loadingScore ? <CircularProgress size={14} /> : <ScienceIcon />}
            onClick={runScore}
            disabled={loadingScore}
          >
            {t('funds.research.score')}
          </Button>
          <Button
            variant="outlined"
            startIcon={loadingAiPicks ? <CircularProgress size={14} /> : <AutoFixHighIcon />}
            onClick={loadAiPicks}
            disabled={loadingAiPicks}
          >
            {t('funds.research.load_ai_picks')}
          </Button>
          <Button
            variant="contained"
            startIcon={loadingRecommend ? <CircularProgress size={14} color="inherit" /> : <AutoFixHighIcon />}
            onClick={runRecommend}
            disabled={loadingRecommend}
          >
            {t('funds.research.recommend')}
          </Button>
          <Button
            variant="text"
            onClick={() => loadReport(false)}
            disabled={loadingReport}
          >
            {t('funds.research.load_report')}
          </Button>
          <Button
            variant="text"
            onClick={() => loadReport(true)}
            disabled={loadingReport}
          >
            {t('funds.research.refresh_report')}
          </Button>
        </Stack>
      </Paper>

      {message && (
        <Alert severity={message.severity} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}

      {cacheState && (
        <Paper elevation={0} sx={{ borderRadius: '12px', border: '1px solid #e2e8f0', p: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            {t('funds.research.cache_status')} - TTL {cacheState.ttl_seconds}s
            {cacheState.age_seconds !== undefined ? ` | Age ${cacheState.age_seconds}s` : ''}
            {cacheState.stale ? ` | ${t('funds.research.cache_stale')}` : ''}
            {cacheState.refreshing ? ` | ${t('funds.research.cache_refreshing')}` : ''}
          </Typography>
        </Paper>
      )}

      {aiPicks.length > 0 && (
        <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', p: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
            {t('funds.research.ai_picks_title')}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            {t('funds.research.ai_picks_subtitle')}
          </Typography>
          <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('funds.research.fund')}</TableCell>
                  <TableCell>{t('funds.research.ai_pick_score')}</TableCell>
                  <TableCell align="right">{t('funds.research.action')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {aiPicks.map((item) => (
                  <TableRow key={item.code} hover>
                    <TableCell>{item.code} {item.name}</TableCell>
                    <TableCell>{item.score?.toFixed?.(2) ?? '-'}</TableCell>
                    <TableCell align="right">
                      <Button
                        variant="text"
                        size="small"
                        onClick={() => {
                          setFundCode(item.code);
                          setMessage({ severity: 'info', text: `${t('funds.research.fund_code')}: ${item.code}` });
                        }}
                      >
                        {t('funds.research.ai_pick_use')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {recommendation && (
        <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', p: 2 }}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} justifyContent="space-between" sx={{ mb: 1.5 }}>
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 800 }}>
                {recommendation.name} ({recommendation.code})
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('funds.research.trade_date')}: {recommendation.trade_date}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Chip color={actionChipColor(recommendation.action)} label={`${t('funds.research.action')}: ${recommendation.action}`} />
              <Chip label={`${t('funds.research.confidence')}: ${(recommendation.confidence * 100).toFixed(0)}%`} />
              {recommendation.confidence_band && (
                <Chip label={`${t('funds.research.confidence_band')}: ${getConfidenceBandLabel(recommendation.confidence_band)}`} />
              )}
            </Stack>
          </Stack>

          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mb: 2 }}>
            <Chip label={`${t('funds.research.base_amount')}: ${recommendation.base_amount}`} />
            <Chip color="primary" label={`${t('funds.research.suggested_amount')}: ${recommendation.suggested_amount}`} />
            <Chip label={`${t('funds.research.multiplier')}: ${recommendation.allocation_multiplier}`} />
          </Stack>

          {recommendation.strategy_explanation && (
            <Alert severity="info" sx={{ mb: 1.5 }}>
              <strong>{t('funds.research.strategy_explanation')}:</strong> {recommendation.strategy_explanation}
            </Alert>
          )}

          {recommendation.user_constraints && (
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ mb: 2 }} flexWrap="wrap">
              <Chip
                variant="outlined"
                label={`${t('funds.research.user_constraints')} - ${t('funds.research.available_cash')}: ${recommendation.user_constraints.available_cash ?? '-'}`}
              />
              <Chip
                variant="outlined"
                label={`${t('funds.research.max_single_day')}: ${recommendation.user_constraints.max_single_day_amount ?? '-'}`}
              />
              <Chip
                variant="outlined"
                label={`${t('funds.research.existing_dca')}: ${recommendation.user_constraints.existing_dca_daily_amount ?? '-'}`}
              />
              <Chip
                variant="outlined"
                label={`${t('funds.research.max_drawdown_tolerance')}: ${recommendation.user_constraints.max_drawdown_tolerance ?? '-'}`}
              />
            </Stack>
          )}

          {recommendation.tactical_boost_reason && recommendation.tactical_boost_reason.length > 0 && (
            <>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                {t('funds.research.tactical_boost_reason')}
              </Typography>
              <Stack spacing={0.6} sx={{ mb: 2 }}>
                {recommendation.tactical_boost_reason.map((item, idx) => (
                  <Typography key={`${item}-${idx}`} variant="body2" color="text.secondary">
                    - {item}
                  </Typography>
                ))}
              </Stack>
            </>
          )}

          {(recommendation.bull_points?.length || recommendation.bear_points?.length || recommendation.disagreement_points?.length) && (
            <>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                {t('funds.research.debate_points')}
              </Typography>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mb: 2 }}>
                <Paper variant="outlined" sx={{ p: 1.2, flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
                    {t('funds.research.bull_points')}
                  </Typography>
                  {(recommendation.bull_points || []).map((item, idx) => (
                    <Typography key={`bull-${idx}`} variant="body2" color="text.secondary">- {item}</Typography>
                  ))}
                </Paper>
                <Paper variant="outlined" sx={{ p: 1.2, flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
                    {t('funds.research.bear_points')}
                  </Typography>
                  {(recommendation.bear_points || []).map((item, idx) => (
                    <Typography key={`bear-${idx}`} variant="body2" color="text.secondary">- {item}</Typography>
                  ))}
                </Paper>
                <Paper variant="outlined" sx={{ p: 1.2, flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
                    {t('funds.research.disagreement_points')}
                  </Typography>
                  {(recommendation.disagreement_points || []).map((item, idx) => (
                    <Typography key={`dis-${idx}`} variant="body2" color="text.secondary">- {item}</Typography>
                  ))}
                </Paper>
              </Stack>
            </>
          )}

          <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
            {t('funds.research.scorecard')}
          </Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ mb: 2 }}>
            <Chip label={`${t('funds.research.total_score')}: ${recommendation.scorecard.total_score}`} />
            <Chip label={`${t('funds.research.quality_score')}: ${recommendation.scorecard.quality_score}`} />
            <Chip label={`${t('funds.research.risk_score')}: ${recommendation.scorecard.risk_return_score}`} />
            <Chip label={`${t('funds.research.valuation_score')}: ${recommendation.scorecard.valuation_position_score}`} />
          </Stack>

          {recommendation.evidence?.length > 0 && (
            <>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                {t('funds.research.evidence')}
              </Typography>
              <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t('funds.research.metric')}</TableCell>
                      <TableCell>{t('funds.research.value')}</TableCell>
                      <TableCell>{t('funds.research.source')}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {recommendation.evidence.slice(0, 12).map((item, idx) => (
                      <TableRow key={`${item.metric}-${idx}`}>
                        <TableCell>{item.metric}</TableCell>
                        <TableCell>{item.value}</TableCell>
                        <TableCell>{item.source}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}
        </Paper>
      )}

      <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', p: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
          {t('funds.research.review_title')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {t('funds.research.review_subtitle')}
        </Typography>

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.2} sx={{ mb: 1.2 }}>
          <TextField
            label={t('funds.research.actual_return_pct')}
            value={reviewActualReturn}
            onChange={(e) => setReviewActualReturn(e.target.value)}
            size="small"
            sx={{ minWidth: 130 }}
          />
          <TextField
            label={t('funds.research.max_drawdown_pct')}
            value={reviewMaxDrawdown}
            onChange={(e) => setReviewMaxDrawdown(e.target.value)}
            size="small"
            sx={{ minWidth: 130 }}
          />
          <TextField
            label={t('funds.research.executed_amount')}
            value={reviewExecutedAmount}
            onChange={(e) => setReviewExecutedAmount(e.target.value)}
            size="small"
            sx={{ minWidth: 130 }}
          />
          <TextField
            select
            label={t('funds.research.market_state')}
            value={reviewMarketState}
            onChange={(e) => setReviewMarketState(e.target.value)}
            size="small"
            sx={{ minWidth: 140 }}
          >
            <MenuItem value="bull">{t('funds.research.market_state_bull')}</MenuItem>
            <MenuItem value="bear">{t('funds.research.market_state_bear')}</MenuItem>
            <MenuItem value="sideways">{t('funds.research.market_state_sideways')}</MenuItem>
            <MenuItem value="volatile">{t('funds.research.market_state_volatile')}</MenuItem>
          </TextField>
          <TextField
            label={t('funds.research.strategy_version')}
            value={reviewStrategyVersion}
            onChange={(e) => setReviewStrategyVersion(e.target.value)}
            size="small"
            sx={{ minWidth: 130 }}
          />
          <TextField
            label={t('funds.research.summary_window')}
            value={summaryWindow}
            onChange={(e) => setSummaryWindow(e.target.value)}
            size="small"
            sx={{ minWidth: 110 }}
          />
          <FormControlLabel
            control={<Switch checked={reviewFollowedPlan} onChange={(_, checked) => setReviewFollowedPlan(checked)} />}
            label={t('funds.research.followed_plan')}
            sx={{ ml: { md: 0.5 } }}
          />
        </Stack>

        <TextField
          label={t('funds.research.reflection')}
          value={reviewReflection}
          onChange={(e) => setReviewReflection(e.target.value)}
          size="small"
          fullWidth
          multiline
          minRows={2}
          sx={{ mb: 1.2 }}
        />

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ mb: 1.2 }}>
          <Button
            variant="contained"
            onClick={submitReview}
            disabled={loadingReviewSubmit}
            startIcon={loadingReviewSubmit ? <CircularProgress size={14} color="inherit" /> : <AutoFixHighIcon />}
          >
            {t('funds.research.submit_review')}
          </Button>
          <Button
            variant="outlined"
            onClick={loadReviewSummary}
            disabled={loadingReviewSummary}
            startIcon={loadingReviewSummary ? <CircularProgress size={14} /> : <RefreshIcon />}
          >
            {t('funds.research.refresh_summary')}
          </Button>
        </Stack>

        {reviewSummary && (
          <Box sx={{ border: '1px solid #e2e8f0', borderRadius: '10px', p: 1.2 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} flexWrap="wrap" sx={{ mb: 1 }}>
              <Chip label={`${t('funds.research.review_count')}: ${reviewSummary.count}`} />
              <Chip label={`${t('funds.research.score_timing')}: ${reviewSummary.averages?.timing ?? '-'}`} />
              <Chip label={`${t('funds.research.score_position')}: ${reviewSummary.averages?.position ?? '-'}`} />
              <Chip label={`${t('funds.research.score_risk')}: ${reviewSummary.averages?.risk ?? '-'}`} />
              <Chip label={`${t('funds.research.score_discipline')}: ${reviewSummary.averages?.discipline ?? '-'}`} />
              <Chip color="primary" label={`${t('funds.research.score_composite')}: ${reviewSummary.averages?.composite ?? '-'}`} />
            </Stack>

            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} flexWrap="wrap" sx={{ mb: 1 }}>
              <Chip label={`${t('funds.research.outcome_success')}: ${reviewSummary.outcome_distribution?.success ?? 0}`} />
              <Chip label={`${t('funds.research.outcome_neutral')}: ${reviewSummary.outcome_distribution?.neutral ?? 0}`} />
              <Chip label={`${t('funds.research.outcome_failure')}: ${reviewSummary.outcome_distribution?.failure ?? 0}`} />
            </Stack>

            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
              {t('funds.research.optimization_suggestions')}
            </Typography>
            <Stack spacing={0.4}>
              {(reviewSummary.suggestions || []).map((item, idx) => (
                <Typography key={`${item}-${idx}`} variant="body2" color="text.secondary">
                  - {item}
                </Typography>
              ))}
            </Stack>
          </Box>
        )}
      </Paper>

      <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', p: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
          {t('funds.research.cases_title')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {t('funds.research.cases_subtitle')}
        </Typography>

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.2} sx={{ mb: 1.2 }}>
          <TextField
            select
            label={t('funds.research.case_outcome_filter')}
            value={caseOutcomeFilter}
            onChange={(e) => setCaseOutcomeFilter(e.target.value)}
            size="small"
            sx={{ minWidth: 150 }}
          >
            <MenuItem value="">{t('funds.research.all')}</MenuItem>
            <MenuItem value="success">{t('funds.research.outcome_success')}</MenuItem>
            <MenuItem value="neutral">{t('funds.research.outcome_neutral')}</MenuItem>
            <MenuItem value="failure">{t('funds.research.outcome_failure')}</MenuItem>
          </TextField>
          <TextField
            select
            label={t('funds.research.case_market_filter')}
            value={caseMarketFilter}
            onChange={(e) => setCaseMarketFilter(e.target.value)}
            size="small"
            sx={{ minWidth: 150 }}
          >
            <MenuItem value="">{t('funds.research.all')}</MenuItem>
            <MenuItem value="bull">{t('funds.research.market_state_bull')}</MenuItem>
            <MenuItem value="bear">{t('funds.research.market_state_bear')}</MenuItem>
            <MenuItem value="sideways">{t('funds.research.market_state_sideways')}</MenuItem>
            <MenuItem value="volatile">{t('funds.research.market_state_volatile')}</MenuItem>
          </TextField>
          <TextField
            label={t('funds.research.case_strategy_filter')}
            value={caseStrategyFilter}
            onChange={(e) => setCaseStrategyFilter(e.target.value)}
            size="small"
            sx={{ minWidth: 150 }}
          />
          <Button
            variant="outlined"
            onClick={loadCaseLibrary}
            disabled={loadingCases}
            startIcon={loadingCases ? <CircularProgress size={14} /> : <RefreshIcon />}
          >
            {t('funds.research.load_cases')}
          </Button>
        </Stack>

        {caseLibrary.length > 0 ? (
          <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('funds.research.trade_date')}</TableCell>
                  <TableCell>{t('funds.research.fund')}</TableCell>
                  <TableCell>{t('funds.research.case_outcome')}</TableCell>
                  <TableCell>{t('funds.research.market_state')}</TableCell>
                  <TableCell>{t('funds.research.strategy_version')}</TableCell>
                  <TableCell>{t('funds.research.case_summary')}</TableCell>
                  <TableCell>{t('funds.research.case_tags')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {caseLibrary.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>{item.trade_date || '-'}</TableCell>
                    <TableCell>{item.fund_code}</TableCell>
                    <TableCell>{item.outcome || '-'}</TableCell>
                    <TableCell>{item.market_state || '-'}</TableCell>
                    <TableCell>{item.strategy_version || '-'}</TableCell>
                    <TableCell>{item.summary || '-'}</TableCell>
                    <TableCell>{(item.tags || []).join(', ') || '-'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Typography variant="body2" color="text.secondary">
            {t('funds.research.case_empty')}
          </Typography>
        )}
      </Paper>

      {scores.length > 0 && (
        <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', p: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 800, mb: 1.5 }}>
            {t('funds.research.score_ranking')}
          </Typography>
          <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('funds.research.fund')}</TableCell>
                  <TableCell>{t('funds.research.total_score')}</TableCell>
                  <TableCell>{t('funds.research.action')}</TableCell>
                  <TableCell>{t('funds.research.filter_status')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {scores.map((row) => (
                  <TableRow key={row.code} hover>
                    <TableCell>{row.code} {row.name}</TableCell>
                    <TableCell>{row.total_score.toFixed(2)}</TableCell>
                    <TableCell>
                      {row.total_score >= 75 ? 'add' : row.total_score >= 45 ? 'hold' : 'pause'}
                    </TableCell>
                    <TableCell>
                      {row.hard_filter_pass ? t('funds.research.filter_pass') : t('funds.research.filter_fail')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {universePreview.length > 0 && (
        <Paper elevation={0} sx={{ borderRadius: '14px', border: '1px solid #e2e8f0', p: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 800, mb: 1.5 }}>
            {t('funds.research.pool_preview')}
          </Typography>
          <TableContainer sx={{ border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('funds.research.fund')}</TableCell>
                  <TableCell>{t('funds.research.type')}</TableCell>
                  <TableCell>{t('funds.research.index_flag')}</TableCell>
                  <TableCell>{t('funds.research.dca_flag')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {universePreview.slice(0, 20).map((item) => (
                  <TableRow key={item.code}>
                    <TableCell>{item.code} {item.name}</TableCell>
                    <TableCell>{item.fund_type || '-'}</TableCell>
                    <TableCell>{item.is_index_fund ? 'Y' : 'N'}</TableCell>
                    <TableCell>{item.is_dca_eligible ? 'Y' : 'N'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}
    </Box>
  );
}
