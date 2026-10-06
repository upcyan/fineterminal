#include "settings.h"

#include <QSettings>
#include <QCryptographicHash>
#include <QRandomGenerator>
#include <QProcessEnvironment>

static QByteArray genSalt()
{
    QByteArray s;
    s.resize(16);
    for (int i = 0; i < 16; ++i)
        s[i] = char(QRandomGenerator::system()->generate() & 0xFF);
    return s.toHex();
}

static QByteArray hashPassword(const QString &plain, const QByteArray &saltHex)
{
    // PBKDF 风格：多轮加盐 SHA-256，足够防本地偷看
    QByteArray data = saltHex + plain.toUtf8();
    for (int i = 0; i < 10000; ++i) {
        data = QCryptographicHash::hash(data, QCryptographicHash::Sha256);
    }
    return data.toHex();
}

Settings &Settings::instance()
{
    static Settings s;
    return s;
}

void Settings::load()
{
    QSettings st(QStringLiteral("FineTerminal"), QStringLiteral("FineTerminal"));
    m_colorScheme = st.value(QStringLiteral("appearance/scheme"), m_colorScheme).toString();
    m_fontFamily = st.value(QStringLiteral("appearance/fontFamily"), m_fontFamily).toString();
    m_fontSize = st.value(QStringLiteral("appearance/fontSize"), m_fontSize).toInt();
    m_opacity = st.value(QStringLiteral("appearance/opacity"), m_opacity).toDouble();
    m_historySize = st.value(QStringLiteral("appearance/historySize"), m_historySize).toInt();
    m_blinkingCursor = st.value(QStringLiteral("appearance/blinkingCursor"), m_blinkingCursor).toBool();

    m_shell = st.value(QStringLiteral("behavior/shell"), QString()).toString();
    m_confirmMultilinePaste = st.value(QStringLiteral("behavior/confirmMultilinePaste"), true).toBool();
    m_trimPaste = st.value(QStringLiteral("behavior/trimPaste"), true).toBool();

    m_passwordHash = st.value(QStringLiteral("security/passwordHash"), QByteArray()).toByteArray();
    m_passwordSalt = st.value(QStringLiteral("security/passwordSalt"), QByteArray()).toByteArray();
    m_lockOnStart = st.value(QStringLiteral("security/lockOnStart"), false).toBool();
    m_lockOnIdle = st.value(QStringLiteral("security/lockOnIdle"), false).toBool();
    m_idleTimeoutMin = st.value(QStringLiteral("security/idleTimeoutMin"), 15).toInt();

    m_quickCommands.clear();
    int n = st.beginReadArray(QStringLiteral("quickCommands"));
    for (int i = 0; i < n; ++i) {
        st.setArrayIndex(i);
        QuickCommand qc;
        qc.name = st.value(QStringLiteral("name")).toString();
        qc.command = st.value(QStringLiteral("command")).toString();
        if (!qc.command.isEmpty())
            m_quickCommands.append(qc);
    }
    st.endArray();
}

void Settings::save()
{
    QSettings st(QStringLiteral("FineTerminal"), QStringLiteral("FineTerminal"));
    st.setValue(QStringLiteral("appearance/scheme"), m_colorScheme);
    st.setValue(QStringLiteral("appearance/fontFamily"), m_fontFamily);
    st.setValue(QStringLiteral("appearance/fontSize"), m_fontSize);
    st.setValue(QStringLiteral("appearance/opacity"), m_opacity);
    st.setValue(QStringLiteral("appearance/historySize"), m_historySize);
    st.setValue(QStringLiteral("appearance/blinkingCursor"), m_blinkingCursor);

    st.setValue(QStringLiteral("behavior/shell"), m_shell);
    st.setValue(QStringLiteral("behavior/confirmMultilinePaste"), m_confirmMultilinePaste);
    st.setValue(QStringLiteral("behavior/trimPaste"), m_trimPaste);

    st.setValue(QStringLiteral("security/passwordHash"), m_passwordHash);
    st.setValue(QStringLiteral("security/passwordSalt"), m_passwordSalt);
    st.setValue(QStringLiteral("security/lockOnStart"), m_lockOnStart);
    st.setValue(QStringLiteral("security/lockOnIdle"), m_lockOnIdle);
    st.setValue(QStringLiteral("security/idleTimeoutMin"), m_idleTimeoutMin);

    st.remove(QStringLiteral("quickCommands"));
    st.beginWriteArray(QStringLiteral("quickCommands"));
    for (int i = 0; i < m_quickCommands.size(); ++i) {
        st.setArrayIndex(i);
        st.setValue(QStringLiteral("name"), m_quickCommands[i].name);
        st.setValue(QStringLiteral("command"), m_quickCommands[i].command);
    }
    st.endArray();
    st.sync();
}

void Settings::setPassword(const QString &plain)
{
    m_passwordSalt = genSalt();
    m_passwordHash = hashPassword(plain, m_passwordSalt);
}

bool Settings::verifyPassword(const QString &plain) const
{
    if (m_passwordHash.isEmpty())
        return true;
    return hashPassword(plain, m_passwordSalt) == m_passwordHash;
}

QFont Settings::terminalFont() const
{
    QFont f(m_fontFamily, m_fontSize);
    f.setStyleHint(QFont::TypeWriter);
    return f;
}

void Settings::setQuickCommands(const QList<QuickCommand> &v)
{
    m_quickCommands = v;
}
