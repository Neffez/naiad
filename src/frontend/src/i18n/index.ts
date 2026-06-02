import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import de from './locales/de.json'
import en from './locales/en.json'

i18n.use(initReactI18next).init({
  resources: { de: { translation: de }, en: { translation: en } },
  lng: localStorage.getItem('naiad_lang') ?? 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

// Keep the document language in sync so assistive tech announces content in the
// right language (and `:lang()` styling works). Updated on every switch.
function syncDocumentLang(lng: string): void {
  document.documentElement.lang = lng.split('-')[0]
}
syncDocumentLang(i18n.language)
i18n.on('languageChanged', syncDocumentLang)

export default i18n
