#include "settingsdialog.h"
#include "lockscreen.h"

#include <QTabWidget>
#include <QComboBox>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QCheckBox>
#include <QLineEdit>
#include <QListWidget>
#include <QPushButton>
#include <QFormLayout>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QDialogButtonBox>
#include <QFontDatabase>
#include <QProcessEnvironment>
#include <QMessageBox>
#include <QDir>

static QStringList availableColorSchemes()
{
    // 读取 qtermwidget 自带配色 + 用户目录
    QStringList names;
    const QStringList dirs = {
        QStringLiteral("/usr/share/qtermwidget5/color-schemes"),
        QDir::homePath() + QStringLiteral("/.local/share/qtermwidget5/color-schemes"),
    };
    for (const QString &d : dirs) {
        const QDir dir(d);
        const auto files = dir.entryList(QStringList() << QStringLiteral("*.colorscheme"), QDir::Files);
        for (const QString &f : files)
            names << f.chopped(11); // 去掉 .colorscheme
    }
    names.removeDuplicates();
    names.sort();
    if (names.isEmpty())
        names << QStringLiteral("DarkPastels") << QStringLiteral("Linux") << QStringLiteral("BlackOnWhite");
    return names;
}

SettingsDialog::SettingsDialog(QWidget *parent)
    : QDialog(parent)
{
    setWindowTitle(tr("FineTerminal 设置"));
    resize(560, 480);

    Settings &st = Settings::instance();

    auto *tabs = new QTabWidget(this);

    // ---------- 外观 ----------
    auto *appearance = new QWidget(this);
    auto *form = new QFormLayout(appearance);

    m_scheme = new QComboBox(appearance);
    m_scheme->addItems(availableColorSchemes());
    m_scheme->setCurrentText(st.colorScheme());
    form->addRow(tr("配色方案"), m_scheme);

    m_fontFamily = new QComboBox(appearance);
    const QFontDatabase fdb;
    const QStringList mono = fdb.families(QFontDatabase::Any);
    for (const QString &f : mono)
        if (QFontInfo(QFont(f)).fixedPitch())
            m_fontFamily->addItem(f);
    if (m_fontFamily->count() == 0)
        m_fontFamily->addItem(QStringLiteral("Monospace"));
    const int fi = m_fontFamily->findText(st.fontFamily());
    if (fi >= 0)
        m_fontFamily->setCurrentIndex(fi);
    m_fontFamily->setEditable(true);
    form->addRow(tr("字体"), m_fontFamily);

    m_fontSize = new QSpinBox(appearance);
    m_fontSize->setRange(6, 40);
    m_fontSize->setValue(st.fontSize());
    form->addRow(tr("字号"), m_fontSize);

    m_opacity = new QDoubleSpinBox(appearance);
    m_opacity->setRange(0.3, 1.0);
    m_opacity->setSingleStep(0.05);
    m_opacity->setValue(st.opacity());
    form->addRow(tr("背景不透明度"), m_opacity);

    m_history = new QSpinBox(appearance);
    m_history->setRange(100, 100000);
    m_history->setSingleStep(1000);
    m_history->setValue(st.historySize());
    form->addRow(tr("回滚缓冲行数"), m_history);

    m_blinkCursor = new QCheckBox(tr("光标闪烁"), appearance);
    m_blinkCursor->setChecked(st.blinkingCursor());
    form->addRow(m_blinkCursor);

    // ---------- 行为 ----------
    auto *behavior = new QWidget(this);
    auto *form2 = new QFormLayout(behavior);

    m_shell = new QLineEdit(behavior);
    m_shell->setPlaceholderText(QProcessEnvironment::systemEnvironment().value(QStringLiteral("SHELL"), QStringLiteral("/bin/bash")));
    m_shell->setText(st.shell());
    form2->addRow(tr("Shell 程序"), m_shell);

    m_confirmPaste = new QCheckBox(tr("粘贴多行内容前确认"), behavior);
    m_confirmPaste->setChecked(st.confirmMultilinePaste());
    form2->addRow(m_confirmPaste);

    m_trimPaste = new QCheckBox(tr("粘贴时去除行尾空白"), behavior);
    m_trimPaste->setChecked(st.trimPaste());
    form2->addRow(m_trimPaste);

    // ---------- 快捷命令 ----------
    auto *quick = new QWidget(this);
    auto *v = new QVBoxLayout(quick);

    m_cmdList = new QListWidget(quick);
    v->addWidget(m_cmdList, 1);

    auto *row = new QHBoxLayout;
    m_cmdName = new QLineEdit(quick);
    m_cmdName->setPlaceholderText(tr("名称，如：磁盘用量"));
    m_cmdText = new QLineEdit(quick);
    m_cmdText->setPlaceholderText(tr("命令，如：df -h"));
    row->addWidget(m_cmdName, 1);
    row->addWidget(m_cmdText, 2);
    v->addLayout(row);

    auto *btnRow = new QHBoxLayout;
    auto *addBtn = new QPushButton(tr("添加"), quick);
    auto *delBtn = new QPushButton(tr("删除"), quick);
    auto *upBtn = new QPushButton(tr("上移"), quick);
    auto *downBtn = new QPushButton(tr("下移"), quick);
    btnRow->addWidget(addBtn);
    btnRow->addWidget(delBtn);
    btnRow->addWidget(upBtn);
    btnRow->addWidget(downBtn);
    btnRow->addStretch();
    v->addLayout(btnRow);

    connect(addBtn, &QPushButton::clicked, this, &SettingsDialog::addCommand);
    connect(delBtn, &QPushButton::clicked, this, &SettingsDialog::removeCommand);
    connect(upBtn, &QPushButton::clicked, [this] { moveCommand(-1); });
    connect(downBtn, &QPushButton::clicked, [this] { moveCommand(1); });

    // ---------- 安全 ----------
    auto *security = new QWidget(this);
    auto *form3 = new QFormLayout(security);

    auto *pwdBtn = new QPushButton(tr("设置 / 修改锁屏密码"), security);
    form3->addRow(tr("锁屏密码"), pwdBtn);

    m_lockOnStart = new QCheckBox(tr("启动时锁定"), security);
    m_lockOnStart->setChecked(st.lockOnStart());
    form3->addRow(m_lockOnStart);

    m_lockOnIdle = new QCheckBox(tr("空闲自动锁定"), security);
    m_lockOnIdle->setChecked(st.lockOnIdle());
    form3->addRow(m_lockOnIdle);

    m_idleMin = new QSpinBox(security);
    m_idleMin->setRange(1, 240);
    m_idleMin->setSuffix(tr(" 分钟"));
    m_idleMin->setValue(st.idleTimeoutMin());
    form3->addRow(tr("空闲阈值"), m_idleMin);

    connect(pwdBtn, &QPushButton::clicked, this, &SettingsDialog::setPasswordClicked);

    tabs->addTab(appearance, tr("外观"));
    tabs->addTab(behavior, tr("行为"));
    tabs->addTab(quick, tr("快捷命令"));
    tabs->addTab(security, tr("安全"));

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &SettingsDialog::saveChanges);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);

    auto *main = new QVBoxLayout(this);
    main->addWidget(tabs);
    main->addWidget(buttons);

    loadCommandsToUi();
}

void SettingsDialog::loadCommandsToUi()
{
    m_cmdList->clear();
    const auto cmds = Settings::instance().quickCommands();
    for (const auto &qc : cmds)
        m_cmdList->addItem(qc.name + QStringLiteral("  —  ") + qc.command);
}

void SettingsDialog::addCommand()
{
    if (m_cmdText->text().isEmpty())
        return;
    Settings &st = Settings::instance();
    auto cmds = st.quickCommands();
    QuickCommand qc;
    qc.name = m_cmdName->text().isEmpty() ? m_cmdText->text() : m_cmdName->text();
    qc.command = m_cmdText->text();
    cmds.append(qc);
    st.setQuickCommands(cmds);
    st.save();
    m_cmdName->clear();
    m_cmdText->clear();
    loadCommandsToUi();
    emit settingsChanged();
}

void SettingsDialog::removeCommand()
{
    const int row = m_cmdList->currentRow();
    if (row < 0)
        return;
    Settings &st = Settings::instance();
    auto cmds = st.quickCommands();
    cmds.removeAt(row);
    st.setQuickCommands(cmds);
    st.save();
    loadCommandsToUi();
    emit settingsChanged();
}

void SettingsDialog::moveCommand(int delta)
{
    const int row = m_cmdList->currentRow();
    if (row < 0)
        return;
    const int to = row + delta;
    Settings &st = Settings::instance();
    auto cmds = st.quickCommands();
    if (to < 0 || to >= cmds.size())
        return;
    cmds.move(row, to);
    st.setQuickCommands(cmds);
    st.save();
    loadCommandsToUi();
    m_cmdList->setCurrentRow(to);
    emit settingsChanged();
}

void SettingsDialog::setPasswordClicked()
{
    LockScreen setup(this);
    setup.setSetupMode(true);
    if (setup.exec() == QDialog::Accepted) {
        QMessageBox::information(this, tr("FineTerminal"), tr("锁屏密码已保存。"));
        emit passwordSet();
    }
}

void SettingsDialog::saveChanges()
{
    Settings &st = Settings::instance();
    st.setColorScheme(m_scheme->currentText());
    st.setFontFamily(m_fontFamily->currentText());
    st.setFontSize(m_fontSize->value());
    st.setOpacity(m_opacity->value());
    st.setHistorySize(m_history->value());
    st.setBlinkingCursor(m_blinkCursor->isChecked());
    st.setShell(m_shell->text().trimmed());
    st.setConfirmMultilinePaste(m_confirmPaste->isChecked());
    st.setTrimPaste(m_trimPaste->isChecked());
    st.setLockOnStart(m_lockOnStart->isChecked());
    st.setLockOnIdle(m_lockOnIdle->isChecked());
    st.setIdleTimeoutMin(m_idleMin->value());
    st.save();
    emit settingsChanged();
    accept();
}
