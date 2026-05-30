const BOARD_SIZE = 15;
const CELL_SIZE = 40;
const PADDING = 20;
const STONE_RADIUS = 16;

const EMPTY = 0;
const BLACK = 1;
const WHITE = 2;

let board = [];
let gameOver = false;
let lastAiStepId = null;
let isSubmitting = false;
let winRateChart = null;
let latestReviewData = null;
let highlightedAiMove = null;
let top3Markers = [];

const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');

const statusEl = document.getElementById('status');
const reasoningEl = document.getElementById('reasoning');
const newGameBtn = document.getElementById('newGameBtn');
const reviewBtn = document.getElementById('reviewBtn');
const downloadBtn = document.getElementById('downloadBtn');
const personalityBtn = document.getElementById('personalityBtn');
const personalityPanel = document.getElementById('personalityPanel');
const personalityLoading = document.getElementById('personalityLoading');
const qaBtn = document.getElementById('qaBtn');
const qaInput = document.getElementById('qaInput');
const answerPanel = document.getElementById('answerPanel') || document.getElementById('qaResult') || document.getElementById('explainPanel');

const reviewPanel = document.getElementById('reviewPanel');
const reviewLoading = document.getElementById('reviewLoading');
const reviewHint = document.getElementById('reviewHint');

const winRateContainer = document.getElementById('winRateContainer');
const winRateCanvas = document.getElementById('winRateChart');

function createEmptyBoard() {
    return Array.from({ length: BOARD_SIZE }, () => Array(BOARD_SIZE).fill(EMPTY));
}

function setStatus(text, type = '') {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.className = 'status';
    if (type) statusEl.classList.add(type);
}

function setReasoning(text) {
    if (reasoningEl) reasoningEl.textContent = text || '';
}

function setBusyState(busy) {
    isSubmitting = busy;
    if (newGameBtn) newGameBtn.disabled = busy;
    if (reviewBtn) reviewBtn.disabled = busy || !gameOver;
    if (downloadBtn) downloadBtn.disabled = busy || !latestReviewData;
    if (personalityBtn) personalityBtn.disabled = busy || !latestReviewData;
    if (qaBtn) qaBtn.disabled = busy;
}

function updateButtons() {
    if (reviewBtn) reviewBtn.disabled = isSubmitting || !gameOver;
    if (newGameBtn) newGameBtn.disabled = isSubmitting;
    if (downloadBtn) downloadBtn.disabled = isSubmitting || !latestReviewData;
    if (personalityBtn) personalityBtn.disabled = isSubmitting || !latestReviewData;
    if (qaBtn) qaBtn.disabled = isSubmitting;
}

function answerPlaceholderHtml() {
    return `
        <p class="placeholder-text">你可以问：</p>
        <ul>
            <li>什么是活三、冲四、双三？</li>
            <li>帮我分析下一步怎么走</li>
            <li>当前局面谁更占优？</li>
            <li>为什么 AI 这样下？</li>
        </ul>
    `;
}

function clearPanels() {
    latestReviewData = null;
    top3Markers = [];

    if (answerPanel) {
        answerPanel.classList.add('placeholder');
        answerPanel.innerHTML = answerPlaceholderHtml();
    }

    if (reviewPanel) {
        reviewPanel.innerHTML = `
            <p class="placeholder-text">复盘结果将显示在这里...</p>
            <ul>
                <li>本局总结</li>
                <li>关键转折点</li>
                <li>失误分析</li>
                <li>改进建议</li>
            </ul>
        `;
    }

    if (personalityPanel) {
        personalityPanel.style.display = 'none';
        personalityPanel.innerHTML = `
            <p class="placeholder-text">人格测试结果将显示在这里...</p>
            <ul>
                <li>人格类型</li>
                <li>风格称号</li>
                <li>优势与风险</li>
                <li>趣味点评</li>
            </ul>
        `;
    }

    if (personalityLoading) personalityLoading.style.display = 'none';
    if (reviewLoading) reviewLoading.style.display = 'none';
    if (reviewHint) reviewHint.style.display = 'block';

    if (winRateContainer) winRateContainer.style.display = 'none';

    if (downloadBtn) {
        downloadBtn.style.display = 'none';
        downloadBtn.disabled = true;
    }

    if (personalityBtn) {
        personalityBtn.style.display = 'none';
        personalityBtn.disabled = true;
    }

    if (winRateChart) {
        winRateChart.destroy();
        winRateChart = null;
    }
}

function updateStatus() {
    if (gameOver) {
        setStatus('对局结束，可生成复盘', 'game-over');
        return;
    }
    setStatus('你的回合', 'your-turn');
}

function isWithinBoard(x, y) {
    return x >= 0 && x < BOARD_SIZE && y >= 0 && y < BOARD_SIZE;
}

function toBoardCoord(clickX, clickY) {
    const x = Math.round((clickX - PADDING) / CELL_SIZE);
    const y = Math.round((clickY - PADDING) / CELL_SIZE);
    return { x, y };
}

function escapeHtml(text) {
    return String(text ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function toCoordLabel(row, col) {
    const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const colText = letters[col] || String(col + 1);
    return `${colText}${row + 1}`;
}

function drawBoard() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#eecfa1';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;

    for (let i = 0; i < BOARD_SIZE; i++) {
        const pos = PADDING + i * CELL_SIZE;
        ctx.beginPath();
        ctx.moveTo(PADDING, pos);
        ctx.lineTo(PADDING + CELL_SIZE * (BOARD_SIZE - 1), pos);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(pos, PADDING);
        ctx.lineTo(pos, PADDING + CELL_SIZE * (BOARD_SIZE - 1));
        ctx.stroke();
    }

    const stars = [
        [3, 3], [7, 3], [11, 3],
        [3, 7], [7, 7], [11, 7],
        [3, 11], [7, 11], [11, 11]
    ];

    ctx.fillStyle = '#333';
    for (const [x, y] of stars) {
        ctx.beginPath();
        ctx.arc(PADDING + x * CELL_SIZE, PADDING + y * CELL_SIZE, 3, 0, Math.PI * 2);
        ctx.fill();
    }

    for (let y = 0; y < BOARD_SIZE; y++) {
        for (let x = 0; x < BOARD_SIZE; x++) {
            if (board[y][x] === EMPTY) continue;
            const cx = PADDING + x * CELL_SIZE;
            const cy = PADDING + y * CELL_SIZE;
            ctx.beginPath();
            ctx.arc(cx, cy, STONE_RADIUS, 0, Math.PI * 2);
            if (board[y][x] === BLACK) {
                ctx.fillStyle = '#111';
                ctx.fill();
            } else {
                ctx.fillStyle = '#f7f7f7';
                ctx.fill();
                ctx.strokeStyle = '#666';
                ctx.stroke();
            }
        }
    }

    if (highlightedAiMove && Number.isInteger(highlightedAiMove.x) && Number.isInteger(highlightedAiMove.y)) {
        const cx = PADDING + highlightedAiMove.x * CELL_SIZE;
        const cy = PADDING + highlightedAiMove.y * CELL_SIZE;

        ctx.save();
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(cx, cy, STONE_RADIUS + 8, 0, Math.PI * 2);
        ctx.stroke();

        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx, cy, STONE_RADIUS + 14, 0, Math.PI * 2);
        ctx.stroke();

        ctx.fillStyle = '#f59e0b';
        ctx.beginPath();
        ctx.arc(cx + 18, cy - 18, 14, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#fff';
        ctx.font = 'bold 12px Arial';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('AI', cx + 18, cy - 18);
        ctx.restore();
    }

    if (Array.isArray(top3Markers) && top3Markers.length) {
        top3Markers.forEach((item, index) => {
            const row = Number.isInteger(item?.row) ? item.row : Array.isArray(item?.move) ? item.move[0] : null;
            const col = Number.isInteger(item?.col) ? item.col : Array.isArray(item?.move) ? item.move[1] : null;
            if (!Number.isInteger(row) || !Number.isInteger(col)) return;
            if (!isWithinBoard(col, row)) return;
            if (board[row][col] !== EMPTY) return;

            const cx = PADDING + col * CELL_SIZE;
            const cy = PADDING + row * CELL_SIZE;
            const rank = index + 1;

            ctx.save();
            ctx.fillStyle = 'rgba(16, 185, 129, 0.18)';
            ctx.beginPath();
            ctx.arc(cx, cy, STONE_RADIUS + 4, 0, Math.PI * 2);
            ctx.fill();

            ctx.strokeStyle = '#10b981';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(cx, cy, STONE_RADIUS + 4, 0, Math.PI * 2);
            ctx.stroke();

            ctx.fillStyle = '#10b981';
            ctx.beginPath();
            ctx.arc(cx + 15, cy + 15, 11, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#fff';
            ctx.font = 'bold 12px Arial';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(String(rank), cx + 15, cy + 15);
            ctx.restore();
        });
    }
}


function extractTop3FromResponse(data) {
    const candidates = [
        data?.data?.top3,
        data?.top3,
        data?.data?.recommendations,
        data?.recommendations,
        data?.data?.moves,
        data?.moves,
        data?.data?.candidates,
        data?.candidates,
    ];

    for (const candidate of candidates) {
        if (!Array.isArray(candidate)) continue;
        const normalized = candidate.map(item => {
            const move = Array.isArray(item?.move)
                ? item.move
                : Array.isArray(item?.position)
                    ? item.position
                    : [item?.row, item?.col];
            const row = Number.isInteger(item?.row) ? item.row : move[0];
            const col = Number.isInteger(item?.col) ? item.col : move[1];
            if (!Number.isInteger(row) || !Number.isInteger(col)) return null;
            return {
                ...item,
                row,
                col,
                coord_label: item?.coord_label || item?.coord || toCoordLabel(row, col),
                reason: item?.reason || item?.why || item?.explanation || item?.summary || ''
            };
        }).filter(Boolean);
        if (normalized.length) return normalized;
    }
    return [];
}

function renderObjectAnswer(payload) {
    if (payload == null) return '<p>暂无回答。</p>';
    if (typeof payload === 'string' || typeof payload === 'number' || typeof payload === 'boolean') {
        return `<p>${escapeHtml(String(payload)).replaceAll('\n', '<br>')}</p>`;
    }
    if (Array.isArray(payload)) {
        if (!payload.length) return '<p>暂无回答。</p>';
        return `<ul>${payload.map(item => `<li>${escapeHtml(typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item))}</li>`).join('')}</ul>`;
    }

    const mainText = [
        payload.answer,
        payload.text,
        payload.explanation,
        payload.summary,
        payload.message,
        payload.content,
        payload.result,
    ].find(v => typeof v === 'string' && v.trim());

    const evidence = Array.isArray(payload.evidence)
        ? payload.evidence
        : Array.isArray(payload.reasons)
            ? payload.reasons
            : Array.isArray(payload.basis)
                ? payload.basis
                : [];

    const alternatives = Array.isArray(payload.alternatives)
        ? payload.alternatives
        : Array.isArray(payload.suggestions)
            ? payload.suggestions
            : Array.isArray(payload.recommendations)
                ? payload.recommendations
                : [];

    let html = '';
    if (mainText) {
        html += `<p>${escapeHtml(mainText).replaceAll('\n', '<br>')}</p>`;
    }

    if (evidence.length) {
        html += `
            <div class="qa-section-block">
                <div class="qa-section-title">依据</div>
                <ul>${evidence.map(item => `<li>${escapeHtml(typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item))}</li>`).join('')}</ul>
            </div>
        `;
    }

    if (alternatives.length) {
        html += `
            <div class="qa-section-block">
                <div class="qa-section-title">补充说明</div>
                <ul>${alternatives.map(item => {
                    if (typeof item === 'object') {
                        const label = (Number.isInteger(item?.row) && Number.isInteger(item?.col))
                            ? `(${item.row}, ${item.col}) · ${item?.coord_label || toCoordLabel(item.row, item.col)}`
                            : '';
                        const reason = item?.reason || item?.why || item?.explanation || item?.summary || '';
                        const parts = [label, reason].filter(Boolean).join('：');
                        return `<li>${escapeHtml(parts || JSON.stringify(item, null, 2))}</li>`;
                    }
                    return `<li>${escapeHtml(String(item))}</li>`;
                }).join('')}</ul>
            </div>
        `;
    }

    if (!html) {
        html = `<pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
    }
    return html;
}

function setAnswerLoading(text = 'AI 分析中...') {
    if (!answerPanel) return;
    answerPanel.classList.remove('placeholder');
    answerPanel.innerHTML = `<p>${escapeHtml(text)}</p>`;
}

function renderQA(data, questionText) {
    // 先从各种可能的响应结构里提取 top3，避免后端字段名稍变就丢失棋盘高亮
    const extractedTop3 = extractTop3FromResponse(data);
    top3Markers = extractedTop3;
    drawBoard();

    if (!answerPanel) return;
    answerPanel.classList.remove('placeholder');

    if (extractedTop3.length) {
        answerPanel.innerHTML = `
            <h3>问答结果</h3>
            <p><strong>问题：</strong>${escapeHtml(questionText || '')}</p>
            <p class="placeholder-text">Top3 点位已同步高亮到左侧棋盘，标记为 1 / 2 / 3。</p>
            ${extractedTop3.map((item, index) => `
                <div class="qa-move-card">
                    <div class="qa-move-title">推荐 ${index + 1}：(${item.row}, ${item.col}) · ${escapeHtml(item.coord_label || '')}</div>
                    <div class="qa-move-reason">${escapeHtml(item.reason || '')}</div>
                </div>
            `).join('')}
        `;
        return;
    }

    const payload = data?.data ?? data?.answer ?? data?.result ?? data;
    answerPanel.innerHTML = `
        <h3>问答结果</h3>
        <p><strong>问题：</strong>${escapeHtml(questionText || '')}</p>
        ${renderObjectAnswer(payload)}
    `;
}

function renderReview(data) {
    if (!reviewPanel) return;
    const summary = data?.summary || '';
    const turningPoints = Array.isArray(data?.turning_points) ? data.turning_points : [];
    const mistakes = Array.isArray(data?.mistakes) ? data.mistakes : [];
    const suggestions = Array.isArray(data?.suggestions) ? data.suggestions : [];
    const evidence = Array.isArray(data?.evidence) ? data.evidence : [];

    reviewPanel.innerHTML = `
        <h3>棋局复盘</h3>
        <p><strong>总结:</strong> ${escapeHtml(summary)}</p>
        <p><strong>关键点</strong></p>
        <ul>${turningPoints.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
        <p><strong>失误</strong></p>
        <ul>${mistakes.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
        <p><strong>建议</strong></p>
        <ul>${suggestions.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
        <p><strong>参考</strong></p>
        <ul>${evidence.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
    `;
}

function renderPersonality(data) {
    if (!personalityPanel) return;

    const personalityType = data?.personality_type || '';
    const title = data?.title || '';
    const description = data?.description || '';
    const strengths = Array.isArray(data?.strengths) ? data.strengths : [];
    const risks = Array.isArray(data?.risks) ? data.risks : [];
    const advice = Array.isArray(data?.advice) ? data.advice : [];
    const funComment = data?.fun_comment || '';

    personalityPanel.style.display = 'block';
    personalityPanel.innerHTML = `
        <h3>棋风人格测试</h3>
        <div class="personality-tag">${escapeHtml(personalityType)}</div>
        <p><strong>称号：</strong>${escapeHtml(title)}</p>
        <p><strong>画像描述：</strong>${escapeHtml(description)}</p>
        <div class="personality-section"><strong>你的优势</strong><ul>${strengths.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>
        <div class="personality-section"><strong>潜在风险</strong><ul>${risks.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>
        <div class="personality-section"><strong>成长建议</strong><ul>${advice.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>
        <div class="personality-fun">${escapeHtml(funComment)}</div>
    `;
}

function renderWinRateChart(series) {
    if (!winRateContainer || !winRateCanvas) return;
    if (!Array.isArray(series) || series.length === 0) {
        winRateContainer.style.display = 'none';
        if (winRateChart) {
            winRateChart.destroy();
            winRateChart = null;
        }
        return;
    }
    if (typeof Chart === 'undefined') return;

    winRateContainer.style.display = 'block';
    const labels = series.map(item => `Step ${item.step}`);
    const values = series.map(item => item.winrate_ai);
    const pointColors = series.map(item => item.player === 'ai' ? '#ef6c00' : '#2b6cb0');

    if (winRateChart) {
        winRateChart.destroy();
        winRateChart = null;
    }

    winRateChart = new Chart(winRateCanvas.getContext('2d'), {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'AI Win Rate (%)',
                data: values,
                borderColor: '#ef6c00',
                backgroundColor: 'rgba(239, 108, 0, 0.12)',
                pointBackgroundColor: pointColors,
                pointBorderColor: pointColors,
                pointRadius: 4,
                pointHoverRadius: 6,
                fill: true,
                tension: 0.35
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                y: { beginAtZero: true, min: 0, max: 100, title: { display: true, text: 'AI Win Rate (%)' } },
                x: { title: { display: true, text: 'Move Number' } }
            }
        }
    });
}

function buildMarkdownReport(reviewData) {
    const summary = reviewData?.summary || 'No summary';
    const turningPoints = Array.isArray(reviewData?.turning_points) ? reviewData.turning_points : [];
    const mistakes = Array.isArray(reviewData?.mistakes) ? reviewData.mistakes : [];
    const suggestions = Array.isArray(reviewData?.suggestions) ? reviewData.suggestions : [];
    const evidence = Array.isArray(reviewData?.evidence) ? reviewData.evidence : [];
    const winrateSeries = Array.isArray(reviewData?.winrate_series) ? reviewData.winrate_series : [];
    const winner = reviewData?.winner || 'unknown';
    const totalSteps = reviewData?.total_steps || 0;

    const bullet = (items) => items.length ? items.map(item => `- ${item}`).join('\n') : '- None';
    const trendLines = winrateSeries.length
        ? winrateSeries.map(item => `- Step ${item.step} (${item.player === 'human' ? 'Black/Human' : 'White/AI'}): AI win rate ${item.winrate_ai}%`).join('\n')
        : '- No data';

    return `# Gomoku Review Report\n\nGenerated at: ${new Date().toLocaleString()}\n\n## Game Overview\n- Winner: ${winner}\n- Total steps: ${totalSteps}\n\n## Summary\n${summary}\n\n## Turning Points\n${bullet(turningPoints)}\n\n## Mistakes\n${bullet(mistakes)}\n\n## Suggestions\n${bullet(suggestions)}\n\n## Evidence\n${bullet(evidence)}\n\n## Win Rate Trend\n${trendLines}\n`;
}

function downloadTextFile(filename, content, mime = 'text/markdown;charset=utf-8') {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

async function initGame() {
    setBusyState(true);
    try {
        const response = await fetch('/api/new-game', { method: 'POST' });
        if (!response.ok) throw new Error(`new-game failed: ${response.status}`);

        const data = await response.json();
        board = Array.isArray(data.board) ? data.board : createEmptyBoard();
        gameOver = Boolean(data.game_over);
        lastAiStepId = null;
        highlightedAiMove = null;
        top3Markers = [];

        clearPanels();
        setReasoning('');
        if (qaInput) qaInput.value = '';
        updateStatus();
        drawBoard();
    } catch (err) {
        console.error(err);
        setStatus('Failed to start new game', 'game-over');
    } finally {
        setBusyState(false);
        updateButtons();
    }
}

async function playTurn(x, y) {
    if (!isWithinBoard(x, y) || board[y][x] !== EMPTY || gameOver || isSubmitting) return;

    const previousBoard = board.map(row => [...row]);
    board[y][x] = BLACK;
    top3Markers = [];
    drawBoard();

    setBusyState(true);
    setStatus('Submitting move...', 'ai-turn');

    try {
        const response = await fetch('/api/play-turn', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x, y })
        });
        if (!response.ok) {
            let message = `play-turn failed: ${response.status}`;
            try { message = await response.text(); } catch (_) {}
            throw new Error(message);
        }

        const data = await response.json();
        board = Array.isArray(data.board) ? data.board : previousBoard;
        gameOver = Boolean(data.game_over);

        if (data.ai_move) {
            if (typeof data.ai_move.step_id === 'number') lastAiStepId = data.ai_move.step_id;
            if (Number.isInteger(data.ai_move.x) && Number.isInteger(data.ai_move.y)) {
                highlightedAiMove = { x: data.ai_move.x, y: data.ai_move.y };
            } else {
                highlightedAiMove = null;
            }
        } else {
            highlightedAiMove = null;
        }

        setReasoning(data.reasoning ? `AI: ${data.reasoning}` : '');
        drawBoard();

        if (gameOver) {
            const winner = data.winner || 'unknown';
            setStatus(`Game Over: ${winner} wins`, 'game-over');
        } else {
            updateStatus();
        }
    } catch (err) {
        console.error(err);
        board = previousBoard;
        highlightedAiMove = null;
        drawBoard();
        setStatus('Move failed', 'game-over');
    } finally {
        setBusyState(false);
        updateButtons();
    }
}

async function askQA() {
    const question = (qaInput?.value || '').trim();
    if (!question) {
        if (answerPanel) {
            answerPanel.classList.remove('placeholder');
            answerPanel.innerHTML = '<p>请先输入一个问题，例如：什么是活三？ / Top3 候选点 / 为什么 AI 这样下？</p>';
        }
        top3Markers = [];
        drawBoard();
        return;
    }

    setBusyState(true);
    setStatus('Generating answer...', 'ai-turn');
    setAnswerLoading('AI 分析中...');
    top3Markers = [];
    drawBoard();

    try {
        const response = await fetch('/api/qa', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ board, question, step_id: lastAiStepId })
        });
        if (!response.ok) {
            let message = `qa failed: ${response.status}`;
            try { message = await response.text(); } catch (_) {}
            throw new Error(message);
        }
        const data = await response.json();
        renderQA(data, question);
        updateStatus();
    } catch (err) {
        console.error(err);
        if (answerPanel) {
            answerPanel.classList.remove('placeholder');
            answerPanel.innerHTML = '<p>AI 问答失败，请稍后再试。</p>';
        }
        top3Markers = [];
        drawBoard();
        setStatus('QA failed', 'game-over');
    } finally {
        setBusyState(false);
        updateButtons();
    }
}

async function askReview() {
    if (!gameOver) {
        setStatus('Finish the game before generating review', 'ai-turn');
        return;
    }

    setBusyState(true);
    setStatus('Generating review...', 'ai-turn');
    if (reviewLoading) reviewLoading.style.display = 'flex';
    if (reviewHint) reviewHint.style.display = 'none';

    if (reviewPanel) {
        reviewPanel.innerHTML = `
            <p class="placeholder-text">正在生成复盘内容...</p>
            <ul>
                <li>分析关键转折点</li>
                <li>识别失误与策略问题</li>
                <li>生成改进建议</li>
                <li>绘制胜率走势</li>
            </ul>
        `;
    }

    try {
        const response = await fetch('/api/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
        if (!response.ok) {
            let message = `review failed: ${response.status}`;
            try { message = await response.text(); } catch (_) {}
            throw new Error(message);
        }
        const data = await response.json();
        latestReviewData = { ...data, winner: data.winner || 'unknown', total_steps: data.total_steps || 0 };
        renderReview(data);
        renderWinRateChart(data.winrate_series || []);

        if (downloadBtn) { downloadBtn.style.display = 'inline-block'; downloadBtn.disabled = false; }
        if (personalityBtn) { personalityBtn.style.display = 'inline-block'; personalityBtn.disabled = false; }
        updateStatus();
    } catch (err) {
        console.error(err);
        setStatus('Review failed', 'game-over');
        if (reviewPanel) {
            reviewPanel.innerHTML = `
                <p class="placeholder-text">复盘生成失败</p>
                <ul><li>请稍后重试</li><li>检查后端 /api/review 是否正常</li></ul>
            `;
        }
    } finally {
        if (reviewLoading) reviewLoading.style.display = 'none';
        setBusyState(false);
        updateButtons();
    }
}

async function askPersonality() {
    if (!latestReviewData) {
        setStatus('Generate review first', 'ai-turn');
        return;
    }

    setBusyState(true);
    setStatus('Generating personality test...', 'ai-turn');
    if (personalityLoading) personalityLoading.style.display = 'flex';
    if (personalityPanel) personalityPanel.style.display = 'none';

    try {
        const response = await fetch('/api/personality-test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
        if (!response.ok) {
            let message = `personality-test failed: ${response.status}`;
            try { message = await response.text(); } catch (_) {}
            throw new Error(message);
        }
        const data = await response.json();
        renderPersonality(data);
        updateStatus();
    } catch (err) {
        console.error(err);
        setStatus('Personality test failed', 'game-over');
        if (personalityPanel) {
            personalityPanel.style.display = 'block';
            personalityPanel.innerHTML = `
                <p class="placeholder-text">人格测试生成失败</p>
                <ul><li>请确认后端 /api/personality-test 已实现</li><li>请先生成复盘结果后再测试</li></ul>
            `;
        }
    } finally {
        if (personalityLoading) personalityLoading.style.display = 'none';
        setBusyState(false);
        updateButtons();
    }
}

function downloadReport() {
    if (!latestReviewData) {
        setStatus('Generate review first', 'ai-turn');
        return;
    }
    const markdown = buildMarkdownReport(latestReviewData);
    downloadTextFile('gomoku_review_report.md', markdown);
}

if (canvas) {
    canvas.addEventListener('click', async (e) => {
        if (gameOver || isSubmitting) return;
        const rect = canvas.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickY = e.clientY - rect.top;
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const { x, y } = toBoardCoord(clickX * scaleX, clickY * scaleY);
        await playTurn(x, y);
    });
}

if (newGameBtn) newGameBtn.addEventListener('click', initGame);
if (reviewBtn) reviewBtn.addEventListener('click', askReview);
if (downloadBtn) downloadBtn.addEventListener('click', downloadReport);
if (personalityBtn) personalityBtn.addEventListener('click', askPersonality);
if (qaBtn) qaBtn.addEventListener('click', askQA);
if (qaInput) {
    qaInput.addEventListener('keydown', async (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            await askQA();
        }
    });
}

initGame();