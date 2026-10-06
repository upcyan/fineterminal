#include "lockscreen.h"
#include "settings.h"

#include <QKeyEvent>
#include <QVBoxLayout>
#include <QTimer>

LockScreen::LockScreen(QWidget *parent)
    : QDialog(parent)
{
    setWindowTitle(tr("FineTerminal 已锁定"));
    setModal(true);
    setFixedSize(420, 240);

    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(28, 28, 28, 24);
    layout->setSpacing(12);

    m_title = new QLabel(tr("🔒 终端已锁定"), this);
    m_title->setStyleSheet(QStringLiteral("font-size: 18px; font-weight: bold;"));
    m_title->setAlignment(Qt::AlignCenter);

    m_edit = new QLineEdit(this);
    m_edit->setEchoMode(QLineEdit::Password);
    m_edit->setPlaceholderText(tr("请输入解锁密码"));
    m_edit->setFocus();

    m_edit2 = new QLineEdit(this);
    m_edit2->setEchoMode(QLineEdit::Password);
    m_edit2->setPlaceholderText(tr("再次输入密码"));

    m_hint = new QLabel(this);
    m_hint->setStyleSheet(QStringLiteral("color: #d33;"));
    m_hint->setAlignment(Qt::AlignCenter);

    m_ok = new QPushButton(tr("解锁"), this);

    layout->addWidget(m_title);
    layout->addWidget(m_edit);
    layout->addWidget(m_edit2);
    layout->addWidget(m_hint);
    layout->addWidget(m_ok);
    layout->addStretch();

    connect(m_ok, &QPushButton::clicked, this, &LockScreen::tryUnlock);
    connect(m_edit, &QLineEdit::returnPressed, this, &LockScreen::tryUnlock);
    connect(m_edit2, &QLineEdit::returnPressed, this, &LockScreen::tryUnlock);
}

void LockScreen::setSetupMode(bool setup)
{
    m_setupMode = setup;
    applySetupUi();
}

void LockScreen::applySetupUi()
{
    if (m_setupMode) {
        m_title->setText(tr("首次使用：请设置锁屏密码"));
        m_edit->setPlaceholderText(tr("新密码"));
        m_edit2->setVisible(true);
        m_ok->setText(tr("保存并启动"));
    } else {
        m_title->setText(tr("🔒 终端已锁定"));
        m_edit->setPlaceholderText(tr("请输入解锁密码"));
        m_edit2->setVisible(false);
        m_ok->setText(tr("解锁"));
    }
}

void LockScreen::showEvent(QShowEvent *e)
{
    QDialog::showEvent(e);
    applySetupUi();
    m_hint->clear();
    m_edit->clear();
    m_edit2->clear();
    m_edit->setFocus();
}

void LockScreen::keyPressEvent(QKeyEvent *e)
{
    // 拦截 Esc，锁屏不能用 Esc 关闭
    if (e->key() == Qt::Key_Escape)
        return;
    QDialog::keyPressEvent(e);
}

void LockScreen::tryUnlock()
{
    Settings &st = Settings::instance();

    if (m_setupMode) {
        const QString p1 = m_edit->text();
        const QString p2 = m_edit2->text();
        if (p1.size() < 4) {
            m_hint->setText(tr("密码至少 4 位"));
            return;
        }
        if (p1 != p2) {
            m_hint->setText(tr("两次输入不一致"));
            return;
        }
        st.setPassword(p1);
        st.setLockOnStart(true);
        st.save();
        accept();
        return;
    }

    if (st.verifyPassword(m_edit->text())) {
        m_failed = 0;
        accept();
        return;
    }

    ++m_failed;
    m_hint->setText(tr("密码错误（第 %1 次）").arg(m_failed));
    m_edit->clear();
    m_edit->setFocus();
    // 连续错 5 次冻结 3 秒
    if (m_failed % 5 == 0) {
        m_ok->setEnabled(false);
        m_edit->setEnabled(false);
        m_hint->setText(tr("错误次数过多，请 3 秒后重试"));
        QTimer::singleShot(3000, this, [this] {
            m_ok->setEnabled(true);
            m_edit->setEnabled(true);
            m_edit->setFocus();
        });
    }
}
