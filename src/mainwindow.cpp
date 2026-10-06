#include "mainwindow.h"
#include "settings.h"
#include "settingsdialog.h"
#include "lockscreen.h"

#include <qtermwidget5/qtermwidget.h>

#include <QTabWidget>
#include <QToolBar>
#include <QToolButton>
#include <QAction>
#include <QTimer>
#include <QEvent>
#include <QCloseEvent>
#include <QShortcut>
#include <QApplication>
#include <QStyle>
#include <QDir>
#include <QProcessEnvironment>

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    setWindowTitle(QStringLiteral("FineTerminal"));
    resize(960, 640);

    m_tabs = new QTabWidget(this);
    m_tabs->setTabsClosable(true);
    m_tabs->setMovable(true);
    m_tabs->setDocumentMode(true);
    setCentralWidget(m_tabs);

    connect(m_tabs, &QTabWidget::tabCloseRequested, this, &MainWindow::closeTab);

    buildToolbar();

    // 快捷键
    addShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+T")), [this] { newTab(); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+W")),
                [this] { closeTab(m_tabs->currentIndex()); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl+Tab")),
                [this] { cycleTab(); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+Tab")),
                [this] { cycleTab(); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+L")), [this] { lockNow(); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl+,")), [this] { showSettings(); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl++")), [this] { zoom(1); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl+-")), [this] { zoom(-1); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl+0")), [this] { zoom(0); });

    // 复制 / 粘贴（终端惯例 Shift 变体）
    addShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+C")),
                [this] { if (auto *t = currentTerminal()) t->copyClipboard(); });
    addShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+V")),
                [this] { if (auto *t = currentTerminal()) t->pasteClipboard(); });

    // 空闲锁定检查
    m_idleTimer = new QTimer(this);
    m_idleTimer->setInterval(30 * 1000);
    connect(m_idleTimer, &QTimer::timeout, this, [this] {
        Settings &st = Settings::instance();
        if (!st.lockOnIdle())
            return;
        if (m_idleIdleSeconds >= st.idleTimeoutMin() * 60)
            lockNow();
        else
            m_idleIdleSeconds += 30;
    });

    qApp->installEventFilter(this);

    applySettings();
    newTab();
}

void MainWindow::addShortcut(const QKeySequence &seq, const std::function<void()> &fn)
{
    auto *sc = new QShortcut(seq, this);
    connect(sc, &QShortcut::activated, this, fn);
}

// ---- 标签管理 ----

QTermWidget *MainWindow::terminalAt(int index) const
{
    return qobject_cast<QTermWidget *>(m_tabs->widget(index));
}

QTermWidget *MainWindow::currentTerminal() const
{
    return terminalAt(m_tabs->currentIndex());
}

void MainWindow::newTab()
{
    Settings &st = Settings::instance();

    auto *term = new QTermWidget(st.historySize(), this);
    term->setColorScheme(st.colorScheme());
    term->setTerminalFont(st.terminalFont());
    term->setTerminalOpacity(st.opacity());
    term->setBlinkingCursor(st.blinkingCursor());
    term->setConfirmMultilinePaste(st.confirmMultilinePaste());
    term->setTrimPastedTrailingNewlines(st.trimPaste());
    term->setKeyBindings(QStringLiteral("Default"));
    term->setScrollBarPosition(QTermWidget::ScrollBarRight);
    term->setAutoClose(true);

    // 中文环境传递
    term->setEnvironment(QProcessEnvironment::systemEnvironment().toStringList());

    const QString shell = st.shell().isEmpty()
                              ? QProcessEnvironment::systemEnvironment().value(QStringLiteral("SHELL"), QStringLiteral("/bin/bash"))
                              : st.shell();
    term->setShellProgram(shell);
    term->setArgs(QStringList() << QStringLiteral("-l"));
    term->setWorkingDirectory(QDir::homePath());

    connect(term, &QTermWidget::finished, this, [this, term] {
        const int i = m_tabs->indexOf(term);
        if (i >= 0)
            closeTab(i);
    });
    connect(term, &QTermWidget::titleChanged, this, &MainWindow::updateTabTitle);

    const int idx = m_tabs->addTab(term,
                                   style()->standardIcon(QStyle::SP_ComputerIcon),
                                   tr("终端 %1").arg(m_tabs->count() + 1));
    m_tabs->setCurrentIndex(idx);
    term->setFocus();
}

void MainWindow::closeTab(int index)
{
    auto *term = terminalAt(index);
    if (!term)
        return;
    m_tabs->removeTab(index);
    term->deleteLater();
    if (m_tabs->count() == 0 && !m_closing) {
        // 最后一个标签关闭时新开一个，避免误触退出
        newTab();
    }
}

void MainWindow::cycleTab()
{
    const int n = m_tabs->count();
    if (n < 2)
        return;
    const QShortcut *sc = qobject_cast<QShortcut *>(sender());
    const bool backward = sc && sc->key() == QKeySequence(QStringLiteral("Ctrl+Shift+Tab"));
    int next = m_tabs->currentIndex() + (backward ? -1 : 1);
    if (next < 0)
        next = n - 1;
    if (next >= n)
        next = 0;
    m_tabs->setCurrentIndex(next);
}

void MainWindow::zoom(int delta)
{
    auto *term = currentTerminal();
    if (!term)
        return;
    QFont f = term->getTerminalFont();
    if (delta == 0) {
        f = Settings::instance().terminalFont();
    } else {
        const int size = qBound(6, f.pointSize() + delta, 40);
        f.setPointSize(size);
    }
    term->setTerminalFont(f);
}

void MainWindow::updateTabTitle()
{
    auto *term = qobject_cast<QTermWidget *>(sender());
    if (!term)
        return;
    const int i = m_tabs->indexOf(term);
    if (i < 0)
        return;
    QString t = term->title().simplified();
    if (t.isEmpty())
        t = tr("终端 %1").arg(i + 1);
    m_tabs->setTabText(i, t);
}

// ---- 工具栏 ----

void MainWindow::buildToolbar()
{
    auto *tb = addToolBar(tr("主工具栏"));
    tb->setMovable(false);

    auto *newBtn = new QToolButton(tb);
    newBtn->setText(tr("+"));
    newBtn->setToolTip(tr("新建标签 (Ctrl+Shift+T)"));
    connect(newBtn, &QToolButton::clicked, this, [this] { newTab(); });
    tb->addWidget(newBtn);

    auto *lockBtn = new QToolButton(tb);
    lockBtn->setIcon(style()->standardIcon(QStyle::SP_DialogYesButton));
    lockBtn->setToolTip(tr("锁定 (Ctrl+Shift+L)"));
    connect(lockBtn, &QToolButton::clicked, this, &MainWindow::lockNow);
    tb->addWidget(lockBtn);

    auto *settingsBtn = new QToolButton(tb);
    settingsBtn->setText(tr("设置"));
    settingsBtn->setToolTip(tr("设置 (Ctrl+,)"));
    connect(settingsBtn, &QToolButton::clicked, this, &MainWindow::showSettings);
    tb->addWidget(settingsBtn);

    m_quickCmdBar = addToolBar(tr("快捷命令"));
    m_quickCmdBar->setMovable(false);
}

void MainWindow::rebuildQuickCommands()
{
    m_quickCmdBar->clear();
    const auto cmds = Settings::instance().quickCommands();
    for (const auto &qc : cmds) {
        auto *btn = new QToolButton(m_quickCmdBar);
        btn->setText(qc.name);
        btn->setToolTip(qc.command);
        const QString cmd = qc.command;
        connect(btn, &QToolButton::clicked, this, [this, cmd] {
            if (auto *term = currentTerminal()) {
                term->sendText(cmd + QStringLiteral("\n"));
                term->setFocus();
            }
        });
        m_quickCmdBar->addWidget(btn);
    }
}

// ---- 设置 / 锁定 ----

void MainWindow::applySettings()
{
    Settings &st = Settings::instance();
    rebuildQuickCommands();
    for (int i = 0; i < m_tabs->count(); ++i) {
        if (auto *term = terminalAt(i)) {
            term->setColorScheme(st.colorScheme());
            term->setTerminalFont(st.terminalFont());
            term->setTerminalOpacity(st.opacity());
            term->setBlinkingCursor(st.blinkingCursor());
            term->setConfirmMultilinePaste(st.confirmMultilinePaste());
            term->setTrimPastedTrailingNewlines(st.trimPaste());
        }
    }
    if (st.lockOnIdle())
        m_idleTimer->start();
    else
        m_idleTimer->stop();
}

void MainWindow::showSettings()
{
    SettingsDialog dlg(this);
    connect(&dlg, &SettingsDialog::settingsChanged, this, &MainWindow::applySettings);
    dlg.exec();
}

void MainWindow::lockNow()
{
    Settings &st = Settings::instance();
    if (!st.hasPassword()) {
        // 没密码时引导设置
        LockScreen setup(this);
        setup.setSetupMode(true);
        setup.exec();
        m_idleIdleSeconds = 0;
        return;
    }
    LockScreen lock(this);
    lock.exec();
    m_idleIdleSeconds = 0;
}

// ---- 事件 ----

bool MainWindow::eventFilter(QObject *obj, QEvent *event)
{
    switch (event->type()) {
    case QEvent::KeyPress:
    case QEvent::MouseButtonPress:
    case QEvent::MouseMove:
        m_idleIdleSeconds = 0;
        break;
    default:
        break;
    }
    return QMainWindow::eventFilter(obj, event);
}

void MainWindow::closeEvent(QCloseEvent *event)
{
    m_closing = true;
    event->accept();
}
