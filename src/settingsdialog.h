#ifndef FINETERMINAL_SETTINGSDIALOG_H
#define FINETERMINAL_SETTINGSDIALOG_H

#include <QDialog>
#include "settings.h"

class QListWidget;
class QLineEdit;
class QComboBox;
class QSpinBox;
class QDoubleSpinBox;
class QCheckBox;
class QDialogButtonBox;

class SettingsDialog : public QDialog
{
    Q_OBJECT
public:
    explicit SettingsDialog(QWidget *parent = nullptr);

signals:
    void settingsChanged();
    void passwordSet();

private slots:
    void saveChanges();
    void addCommand();
    void removeCommand();
    void moveCommand(int delta);
    void setPasswordClicked();

private:
    void loadCommandsToUi();

    QComboBox *m_scheme;
    QComboBox *m_fontFamily;
    QSpinBox *m_fontSize;
    QDoubleSpinBox *m_opacity;
    QSpinBox *m_history;
    QCheckBox *m_blinkCursor;
    QLineEdit *m_shell;
    QCheckBox *m_confirmPaste;
    QCheckBox *m_trimPaste;

    QListWidget *m_cmdList;
    QLineEdit *m_cmdName;
    QLineEdit *m_cmdText;

    QCheckBox *m_lockOnStart;
    QCheckBox *m_lockOnIdle;
    QSpinBox *m_idleMin;
};

#endif
