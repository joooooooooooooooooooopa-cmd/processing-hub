import { MonitorDown, FileJson, MessageSquare } from 'lucide-react'
import BottomSheet from './BottomSheet'

interface Props {
  onClose: () => void
}

export default function ExportInstructions({ onClose }: Props) {
  return (
    <BottomSheet title="Как экспортировать чат" onClose={onClose}>
      <div className="space-y-4 text-sm text-gray-300">
        {/* Single chat */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <MessageSquare size={16} className="text-emerald-400" />
            <span className="font-medium text-white">Экспорт одного чата</span>
          </div>
          <ol className="space-y-1.5 pl-4 border-l border-emerald-500/20">
            <li className="pl-2">1. Откройте <span className="text-emerald-400">Telegram Desktop</span></li>
            <li className="pl-2">2. Откройте нужный чат с мерчантом</li>
            <li className="pl-2">3. Нажмите <span className="text-white font-mono bg-[#111827] px-1.5 py-0.5 rounded">...</span> в правом верхнем углу</li>
            <li className="pl-2">4. Выберите <span className="text-white">"Export chat history"</span></li>
            <li className="pl-2">5. Формат: <span className="text-emerald-400">Machine-readable JSON</span></li>
            <li className="pl-2">6. Снимите галочки с Photos, Videos, Files</li>
            <li className="pl-2">7. Нажмите <span className="text-white">Export</span></li>
          </ol>
        </div>

        {/* Full export */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <MonitorDown size={16} className="text-emerald-400" />
            <span className="font-medium text-white">Полная выгрузка всех чатов</span>
          </div>
          <ol className="space-y-1.5 pl-4 border-l border-emerald-500/20">
            <li className="pl-2">1. Telegram Desktop &rarr; <span className="text-white">Настройки</span> &rarr; <span className="text-white">Продвинутые</span></li>
            <li className="pl-2">2. <span className="text-white">"Экспорт данных Telegram"</span></li>
            <li className="pl-2">3. Уберите все медиа, оставьте только <span className="text-emerald-400">Чаты</span></li>
            <li className="pl-2">4. Формат: <span className="text-emerald-400">Machine-readable JSON</span></li>
            <li className="pl-2">5. Загрузите полученный файл сюда</li>
          </ol>
        </div>

        {/* File format */}
        <div className="flex items-start gap-2 p-3 rounded-xl bg-[#111827] border border-emerald-500/10">
          <FileJson size={16} className="text-emerald-400 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-gray-400">
            Поддерживаемые форматы: <span className="text-white">.json</span> (result.json) и <span className="text-white">.zip</span> (архив экспорта).
            Максимальный размер: 20 МБ.
          </div>
        </div>
      </div>
    </BottomSheet>
  )
}
