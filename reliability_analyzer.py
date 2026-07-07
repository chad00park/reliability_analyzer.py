import os
import re
import sys
import threading
import time
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# PDF 출력을 위한 라이브러리
try:
    from matplotlib.backends.backend_pdf import PdfPages
except ImportError:
    pass

# 한글 깨짐 방지
import matplotlib.font_manager as fm
try:
    font_location = "C:/Windows/Fonts/malgun.ttf"
    font_name = fm.FontProperties(fname=font_location).get_name()
    matplotlib.rc('font', family=font_name)
except:
    pass

class DataAnalysisApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reliability Data Analyzer v3.4 - [Precise Alignment]")
        self.geometry("1450x950")
        self.center_window(self, 1450, 950)
        
        self.raw_files_data = {}  
        self.parameter_list = []
        self.selected_parameters = []
        self.lot_groups = {}
        
        self.lot_display_names = {}
        self.cached_plots = {} 
        
        # 인터랙티브 상태 저장소
        self.custom_colors = {}   # {(lot, param, unit): color_str}
        self.deleted_units = {}    # {(lot, param): set(unit, ...)}
        self.undo_stack = []       # 작업 히스토리용 스택
        
        self.is_delta_mode = tk.BooleanVar(value=False)
        self.init_upload_menu()
        
    def center_window(self, win, w, h):
        win.update_idletasks()
        ws = win.winfo_screenwidth()
        hs = win.winfo_screenheight()
        x = (ws / 2) - (w / 2)
        y = (hs / 2) - (h / 2)
        win.geometry(f'{w}x{h}+{int(x)}+{int(y)}')

    def init_upload_menu(self):
        for widget in self.winfo_children(): widget.destroy()
        f = tk.Frame(self, pady=100)
        f.pack(expand=True, fill=tk.BOTH)
        tk.Label(f, text="Step 1: Smart Data Batch Upload", font=("Arial", 18, "bold")).pack(pady=10)
        tk.Button(f, text="파일 일괄 선택 (Lot/Read-out 혼합 가능)", font=("Arial", 12, "bold"), 
                  bg="#2b579a", fg="white", padx=20, pady=10, command=self.handle_file_upload).pack(pady=20)

    def parse_filename_info(self, filename):
        lot_match = re.search(r'(lot\s*\d+)', filename, re.IGNORECASE)
        lot_str = lot_match.group(1).upper().replace(" ", "") if lot_match else "UNKNOWN_LOT"
        ro_match = re.search(r'(\d+\s*(?:hr|cyc|min|sec|day))', filename, re.IGNORECASE)
        ro_str = ro_match.group(1).lower().replace(" ", "") if ro_match else filename
        ro_num = int(re.findall(r'\d+', ro_str)[0]) if re.findall(r'\d+', ro_str) else 99999
        return lot_str, ro_str, ro_num

    def smart_read_csv_or_excel(self, path):
        if path.endswith('.csv'):
            max_cols = 0
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    col_count = len(line.split(','))
                    if col_count > max_cols: max_cols = col_count
            return pd.read_csv(path, header=None, names=range(max_cols), engine='python')
        else:
            return pd.read_excel(path, header=None)

    def handle_file_upload(self):
        files = filedialog.askopenfilenames(title="파일 선택", filetypes=[("Data Files", "*.csv *.xlsx *.xls")])
        if not files: return
        
        m = tk.Toplevel(self); m.title("Mode"); m.transient(self); m.grab_set()
        self.center_window(m, 300, 120)
        
        tk.Label(m, text="데이터 유형 선택", font=("Arial", 10, "bold")).pack(pady=10)
        f = tk.Frame(m); f.pack()
        tk.Button(f, text="Discrete", width=10, command=lambda: self.start_proc(files, "Discrete", m)).pack(side=tk.LEFT, padx=5)
        tk.Button(f, text="Module", width=10, command=lambda: self.start_proc(files, "Module", m)).pack(side=tk.LEFT, padx=5)

    def start_proc(self, files, mode, win):
        self.data_mode = mode; win.destroy(); self.process_files(files)

    def process_files(self, files):
        try:
            # 1. 메인 레이아웃 및 기준점 행 찾기
            df_s = self.smart_read_csv_or_excel(files[0])
            p_idx, u_idx, sample_idx = None, None, None
            
            for i, r in df_s.iterrows():
                val_first_col = str(r.iloc[0]).strip().lower().replace(" ", "")
                if "parameter" in val_first_col: p_idx = i
                if "unit" in val_first_col: u_idx = i
                if "sample" in val_first_col: sample_idx = i # 2. 'sample' 행 인덱스 저장

            if p_idx is None or u_idx is None: 
                raise ValueError("'Parameter' 혹은 'Unit' 정보를 원본 파일 1열에서 찾을 수 없습니다.")
            
            # 만약 sample 행이 명시적으로 발견되지 않았다면, 데이터 시작 기준행을 차선책으로 지정
            if sample_idx is None:
                sample_idx = max(p_idx, u_idx) + 1

            temp_data, all_p, self.lot_groups = {}, set(), {}
            
            # 파일 리스트 정렬 후 로드 진행
            for path in files:
                fname = os.path.basename(path)
                lot, ro, ro_n = self.parse_filename_info(fname)
                df = self.smart_read_csv_or_excel(path)
                
                # 2. X축 시료 고유 명칭 행 추출 연동 (첫 파일에서 찾아낸 고정된 sample_idx 행 강제 적용)
                # 1열 이후(인덱스 1번부터 끝까지)의 데이터를 시료 리스트로 수집합니다.
                units = df.iloc[sample_idx, 1:].dropna().astype(str).tolist()
                
                d_start = max(p_idx, u_idx) + 1
                raw_p = df.iloc[p_idx, 1:].tolist()
                raw_u = df.iloc[u_idx, 1:].tolist()
                
                final_p, prefix = [], ""
                for p in raw_p:
                    ps = str(p).strip() if not pd.isna(p) else ""
                    if self.data_mode == "Module" and ps.lower().startswith("cont_"):
                        prefix = ps.split('_')[1]; final_p.append(ps)
                    else:
                        final_p.append(f"{prefix}_{ps}" if prefix and self.data_mode == "Module" else ps)
                
                counts = {}; numbered_p = []
                for p in final_p:
                    if not p: numbered_p.append(""); continue
                    counts[p] = counts.get(p, 0) + 1; numbered_p.append(p)
                cur = {}
                for idx, p in enumerate(numbered_p):
                    if p and counts[p] > 1:
                        cur[p] = cur.get(p, 0) + 1; numbered_p[idx] = f"{p}{cur[p]}"

                p_dict = {}
                for c_idx, pn in enumerate(numbered_p):
                    if not pn or "cont_" in pn.lower(): continue
                    un = str(raw_u[c_idx]).strip() if c_idx < len(raw_u) and not pd.isna(raw_u[c_idx]) else ""
                    if not un: continue
                    
                    vals = pd.to_numeric(df.iloc[d_start:, c_idx+1], errors='coerce').tolist()
                    vals = vals[:len(units)]
                    if all(v is None or np.isnan(v) for v in vals): continue
                    
                    # 수집된 시료 개수 정보 매칭 맵 구축
                    p_dict[pn] = {'unit': un, 'values': vals, 'units_map': units[:len(vals)]}
                    all_p.add(pn)
                
                temp_data[fname] = {'lot': lot, 'ro': ro, 'ro_num': ro_n, 'params': p_dict}
                if lot not in self.lot_groups: self.lot_groups[lot] = []
                self.lot_groups[lot].append(fname)

            self.parameter_list = sorted(list(all_p))
            self.raw_files_data = temp_data
            
            for l in self.lot_groups: 
                self.lot_groups[l].sort(key=lambda x: self.raw_files_data[x]['ro_num'])
                self.lot_display_names[l] = l
                
            self.init_analysis_menu()
        except Exception as e: messagebox.showerror("Error", str(e))

    def init_analysis_menu(self):
        for widget in self.winfo_children(): widget.destroy()
        
        t = tk.Frame(self, bg="#f4f4f4", pady=10, padx=10); t.pack(fill=tk.X)
        ctrl_f = tk.LabelFrame(t, text="Advanced Analysis Control", font=("Arial", 9, "bold"), bg="#f4f4f4", padx=10)
        ctrl_f.pack(side=tk.RIGHT, padx=10)
        
        tk.Checkbutton(ctrl_f, text="Delta Mode (%)", variable=self.is_delta_mode, bg="#f4f4f4", command=self.start_async_render).pack(side=tk.LEFT, padx=5)
        
        # 4. 되돌리기 버튼 기동
        tk.Button(ctrl_f, text="↩ 되돌리기 (Undo)", font=("Arial", 9, "bold"), bg="#7f8c8d", fg="white", command=self.perform_undo).pack(side=tk.LEFT, padx=5)
        
        # 5. PDF 보고서 출력 다운로드 버튼 컴백 복구
        tk.Button(ctrl_f, text="📄 PDF 리포트 저장", font=("Arial", 9, "bold"), bg="#c0392b", fg="white", command=self.export_to_pdf).pack(side=tk.LEFT, padx=5)

        tk.Label(t, text="Parameter Selector (다중 선택 가능):", font=("Arial", 11, "bold"), bg="#f4f4f4").pack(anchor="w")
        lf = tk.Frame(t); lf.pack(fill=tk.X, pady=5)
        
        self.param_listbox = tk.Listbox(lf, selectmode=tk.EXTENDED, height=6, font=("Consolas", 10))
        self.param_listbox.pack(fill=tk.X, side=tk.LEFT, expand=True)
        sb = ttk.Scrollbar(lf, command=self.param_listbox.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.param_listbox.config(yscrollcommand=sb.set)
        
        self.param_listbox.insert(tk.END, "★ 전체 선택")
        for p in self.parameter_list: self.param_listbox.insert(tk.END, p)
        self.param_listbox.selection_set(0)

        btn_f = tk.Frame(t, bg="#f4f4f4"); btn_f.pack(fill=tk.X)
        tk.Button(btn_f, text="그래프 그리기", bg="#107c41", fg="white", font=("Arial", 10, "bold"), command=self.start_async_render).pack(side=tk.LEFT, padx=5)
        
        c = tk.Frame(self); c.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(c, highlightthickness=0)
        self.scrollable_frame = tk.Frame(self.canvas)
        sb_v = ttk.Scrollbar(c, orient="vertical", command=self.canvas.yview); sb_v.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=sb_v.set)
        
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))
        
        self.canvas.bind_all("<MouseWheel>", self._on_mouse_wheel)
        self.start_async_render()

    def _on_mouse_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def start_async_render(self):
        selections = self.param_listbox.curselection()
        sel_items = [self.param_listbox.get(i) for i in selections]
        
        if "★ 전체 선택" in sel_items: self.selected_parameters = self.parameter_list.copy()
        else: self.selected_parameters = [v for v in sel_items if v != "★ 전체 선택"]
            
        if not self.selected_parameters: return
        
        popup = tk.Toplevel(self); popup.title("Processing"); popup.transient(self); popup.grab_set()
        self.center_window(popup, 350, 120)
        
        tk.Label(popup, text="신뢰성 데이터를 실시간 분석 중입니다...", font=("Arial", 10, "bold")).pack(pady=10)
        p_bar = ttk.Progressbar(popup, length=280, mode='determinate'); p_bar.pack(pady=5)
        lbl_status = tk.Label(popup, text="0%", font=("Arial", 9)); lbl_status.pack()
        
        threading.Thread(target=self.render_analysis_worker, args=(popup, p_bar, lbl_status), daemon=True).start()

    def render_analysis_worker(self, popup, p_bar, lbl_status):
        total_steps = len(self.lot_groups) * len(self.selected_parameters)
        if total_steps == 0: return
        current_step = 0

        prepared_data = []
        base_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        for lot in sorted(self.lot_groups.keys()):
            lot_files = self.lot_groups[lot]
            prepared_data.append(('title', lot, None))
            if self.data_mode == "Module": prepared_data.append(('start_grid', lot, None))

            for param in self.selected_parameters:
                unit_str = ""; initial_vals = {}
                for fn in lot_files:
                    if param in self.raw_files_data[fn]['params']:
                        unit_str = self.raw_files_data[fn]['params'][param]['unit']; break
                if not unit_str:
                    current_step += 1; continue

                if self.is_delta_mode.get():
                    ref_fn = lot_files[0]
                    if param in self.raw_files_data[ref_fn]['params']:
                        p_ref = self.raw_files_data[ref_fn]['params'][param]
                        for u_id, v in zip(p_ref['units_map'], p_ref['values']):
                            if v is not None and not np.isnan(v) and v != 0: initial_vals[u_id] = v

                lines_dataset = []
                del_set = self.deleted_units.get((lot, param), set())

                for f_idx, filename in enumerate(lot_files):
                    if param not in self.raw_files_data[filename]['params']: continue
                    p_info = self.raw_files_data[filename]['params'][param]
                    ro_lbl = self.raw_files_data[filename]['ro']
                    
                    px, py, pc, punit = [], [], [] ,[]
                    for ux, uy in zip(p_info['units_map'], p_info['values']):
                        if uy is None or np.isnan(uy): continue
                        if str(ux) in del_set: continue  # 사용자 삭제 데이터 필터 제외 탈락
                        
                        val_to_plot = uy
                        if self.is_delta_mode.get():
                            if ux in initial_vals: val_to_plot = 100 * (uy - initial_vals[ux]) / initial_vals[ux]
                            else: continue
                        
                        px.append(str(ux))
                        py.append(val_to_plot)
                        punit.append(str(ux))
                        
                        c_key = (lot, param, str(ux))
                        if c_key in self.custom_colors:
                            pc.append(self.custom_colors[c_key])
                        else:
                            pc.append(base_colors[f_idx % len(base_colors)])

                    if px:
                        lines_dataset.append((px, py, pc, punit, ro_lbl, base_colors[f_idx % len(base_colors)]))
                
                display_unit = "%" if self.is_delta_mode.get() else unit_str
                prepared_data.append(('plot', lot, {
                    'param_name': param,
                    'base_title': f"{param} ({display_unit})",
                    'dataset': lines_dataset
                }))
                
                current_step += 1
                pct = int((current_step / total_steps) * 100)
                self.after(0, lambda p=pct: [p_bar.config(value=p), lbl_status.config(text=f"{p}%")])

            # Box Plots
            prepared_data.append(('start_box_grid', lot, None))
            for param in self.selected_parameters:
                b_data, a_labels, b_cols, stats = [], [], [], []
                del_set = self.deleted_units.get((lot, param), set())

                for f_idx, fn in enumerate(lot_files):
                    if param in self.raw_files_data[fn]['params']:
                        p_info = self.raw_files_data[fn]['params'][param]
                        
                        vals = []
                        for ux, uy in zip(p_info['units_map'], p_info['values']):
                            if uy is not None and not np.isnan(uy) and str(ux) not in del_set:
                                vals.append(uy)
                                
                        if vals:
                            b_data.append(vals)
                            a_labels.append(self.raw_files_data[fn]['ro'])
                            b_cols.append(base_colors[f_idx % len(base_colors)])
                            stats.append(f"[{self.raw_files_data[fn]['ro']}]\nAvg:{np.mean(vals):.1f}\nStd:{np.std(vals):.1f}")
                if not b_data: continue

                prepared_data.append(('box_plot', lot, {
                    'base_title': f"{param} Dist",
                    'b_data': b_data, 'a_labels': a_labels, 'b_cols': b_cols, 'stats': stats
                }))

        self.after(0, lambda: self.execute_ui_rendering(prepared_data, popup))

    def execute_ui_rendering(self, commands, popup):
        for w in self.scrollable_frame.winfo_children(): w.destroy()
        
        self.cached_plots = {} 
        current_frame, box_frame = None, None
        grid_idx, box_idx = 0, 0
        
        for cmd_type, lot_key, meta in commands:
            if cmd_type == 'title':
                header_f = tk.Frame(self.scrollable_frame, bg="#eaf2f8", pady=6)
                header_f.pack(fill=tk.X, padx=10, pady=5)
                
                lbl = tk.Label(header_f, text=f"■ [{self.lot_display_names[lot_key]}] Lot Analysis", font=("Arial", 13, "bold"), fg="#1e3799", bg="#eaf2f8")
                lbl.pack(side=tk.LEFT, padx=10)
                
                # 1. 복수 Lot 개별 관리 가능한 독립 변환 인터페이스 세팅
                rename_f = tk.Frame(header_f, bg="#eaf2f8")
                rename_f.pack(side=tk.RIGHT, padx=15)
                tk.Label(rename_f, text="해당 Lot 명칭 변경:", font=("Arial", 9), bg="#eaf2f8").pack(side=tk.LEFT, padx=2)
                
                ent = tk.Entry(rename_f, width=15, font=("Arial", 9))
                ent.insert(0, self.lot_display_names[lot_key])
                ent.pack(side=tk.LEFT, padx=5)
                
                btn = tk.Button(rename_f, text="변경", font=("Arial", 8, "bold"), bg="#546e7a", fg="white",
                                command=lambda l=lot_key, e=ent: self.update_lot_name(l, e.get()))
                btn.pack(side=tk.LEFT)
                
                if lot_key not in self.cached_plots: self.cached_plots[lot_key] = {'labels': [], 'canvases': []}
                self.cached_plots[lot_key]['labels'].append(lbl)
            
            elif cmd_type == 'start_grid':
                current_frame = tk.Frame(self.scrollable_frame)
                current_frame.pack(fill=tk.X, padx=15, pady=5)
                for c in range(3): current_frame.grid_columnconfigure(c, weight=1)
                grid_idx = 0
                
            elif cmd_type == 'plot':
                fig_w = 4.2 if self.data_mode == "Module" else 13.0
                fig_h = 2.5 if self.data_mode == "Module" else 2.2
                fig, ax = plt.subplots(figsize=(fig_w, fig_h))
                
                param_name = meta['param_name']
                
                for px, py, pc, punit, ro_lbl, b_col in meta['dataset']:
                    ax.plot(px, py, color=b_col, alpha=0.5, zorder=1)
                    scatter = ax.scatter(px, py, color=pc, s=45, label=ro_lbl, zorder=3, picker=True)
                    scatter.__dict__['metadata'] = {'lot': lot_key, 'param': param_name, 'units': punit, 'ro': ro_lbl}
                
                fig.__dict__['base_title'] = meta['base_title']
                ax.set_title(f"[{self.lot_display_names[lot_key]}] {meta['base_title']}", fontsize=9, weight='bold')
                ax.grid(True, linestyle=":", alpha=0.5)
                
                # 3. 레전드 박스가 그래프 내부 빈 공간을 찾되 가리지 않도록 자동 최적화
                ax.legend(loc="best", fontsize=7, framealpha=0.8)
                plt.tight_layout()

                if self.data_mode == "Module" and current_frame:
                    cell = tk.Frame(current_frame, bd=1, relief=tk.RIDGE, bg="white")
                    cell.grid(row=grid_idx//3, column=grid_idx%3, padx=4, pady=4, sticky="nsew")
                    canvas = FigureCanvasTkAgg(fig, master=cell)
                    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
                    grid_idx += 1
                else:
                    cell = tk.Frame(self.scrollable_frame, bd=1, relief=tk.RIDGE, bg="white")
                    cell.pack(fill=tk.X, padx=15, pady=4)
                    canvas = FigureCanvasTkAgg(fig, master=cell)
                    canvas.get_tk_widget().pack(fill=tk.X, expand=True)
                
                fig.canvas.mpl_connect('pick_event', self.on_chart_point_clicked)
                self.cached_plots[lot_key]['canvases'].append((fig, canvas))
                plt.close(fig)
                
            elif cmd_type == 'start_box_grid':
                box_frame = tk.Frame(self.scrollable_frame, bg="#f9f9f9")
                box_frame.pack(fill=tk.X, padx=15, pady=10)
                for c in range(4): box_frame.grid_columnconfigure(c, weight=1)
                box_idx = 0
                
            elif cmd_type == 'box_plot':
                fig, ax = plt.subplots(figsize=(3.2, 2.8))
                bp = ax.boxplot(meta['b_data'], patch_artist=True)
                ax.set_xticks(range(1, len(meta['a_labels']) + 1))
                ax.set_xticklabels(meta['a_labels'], fontsize=8)
                for patch, color in zip(bp['boxes'], meta['b_cols']): 
                    patch.set_facecolor(color); patch.set_alpha(0.6)
                
                fig.__dict__['base_title'] = meta['base_title']
                ax.set_title(f"[{self.lot_display_names[lot_key]}] {meta['base_title']}", fontsize=9, weight='bold')
                ax.grid(True, alpha=0.3)
                plt.tight_layout()

                bb = tk.Frame(box_frame, bd=1, relief=tk.GROOVE, bg="white")
                bb.grid(row=box_idx//4, column=box_idx%4, padx=5, pady=5, sticky="nsew")
                box_idx += 1
                
                canvas = FigureCanvasTkAgg(fig, master=bb)
                canvas.get_tk_widget().pack()
                sf = tk.Frame(bb, bg="#fafafa"); sf.pack(fill=tk.X)
                for s in meta['stats']: 
                    tk.Label(sf, text=s, font=("Arial", 7), bg="#fafafa", justify=tk.LEFT).pack(anchor="w", padx=5)
                
                self.cached_plots[lot_key]['canvases'].append((fig, canvas))
                plt.close(fig)

        if popup: 
            popup.grab_release(); popup.destroy()

    def on_chart_point_clicked(self, event):
        """4. 특정 데이터 마우스 포인트 피킹 선택 컨트롤러"""
        scatter = event.artist
        if 'metadata' not in scatter.__dict__: return
        
        meta = scatter.__dict__['metadata']
        ind = event.ind[0]
        
        lot = meta['lot']
        param = meta['param']
        unit_id = meta['units'][ind]
        ro_info = meta['ro']
        
        m = tk.Toplevel(self)
        m.title("Interactive Data Editor")
        m.geometry("450x180")
        self.center_window(m, 450, 180)
        m.transient(self); m.grab_set()
        
        tk.Label(m, text=f"선택한 시료 번호: {unit_id} ({ro_info})", font=("Arial", 11, "bold"), fg="#111111").pack(pady=10)
        
        # 4. 차트 기본색(Tab10)군과 완전 매칭을 피한 가독성 최상급 5개 커스텀 버튼 색상셋 제공 (빨간색 필두)
        color_section = tk.LabelFrame(m, text="원하는 변경 색상 선택 (그래프 중복 방지 컬러셋)", font=("Arial", 9))
        color_section.pack(fill=tk.X, padx=15, pady=5)
        
        distinct_palette = [
            ("🔴 빨강", "#e74c3c"),
            ("🔵 군청", "#0a3d62"),
            ("🟢 연두", "#2ed573"),
            ("🟣 보라", "#8854d0"),
            ("🟠 주황", "#fa8231")
        ]
        
        for text, hex_code in distinct_palette:
            btn = tk.Button(color_section, text=text, font=("Arial", 8, "bold"), bg=hex_code, fg="white", padx=4,
                            command=lambda l=lot, p=param, u=unit_id, c=hex_code: [m.destroy(), self.apply_point_color(l, p, u, c)])
            btn.pack(side=tk.LEFT, expand=True, padx=2, pady=5)
            
        action_f = tk.Frame(m); action_f.pack(pady=10)
        tk.Button(action_f, text="🗑️ 해당 시료 데이터 삭제 (Box연동)", bg="#2c3e50", fg="white", font=("Arial", 9, "bold"),
                  command=lambda: [m.destroy(), self.delete_target_unit(lot, param, unit_id)]).pack(side=tk.LEFT, padx=10)
        tk.Button(action_f, text="창 닫기", command=m.destroy, font=("Arial", 9)).pack(side=tk.LEFT, padx=10)

    def apply_point_color(self, lot, param, unit_id, chosen_color):
        c_key = (lot, param, unit_id)
        old_color = self.custom_colors.get(c_key, None)
        self.undo_stack.append(('color', c_key, old_color))
        self.custom_colors[c_key] = chosen_color
        self.refresh_current_charts()

    def delete_target_unit(self, lot, param, unit_id):
        key = (lot, param)
        if key not in self.deleted_units:
            self.deleted_units[key] = set()
            
        self.deleted_units[key].add(unit_id)
        self.undo_stack.append(('delete', key, unit_id))
        self.refresh_current_charts()

    def perform_undo(self):
        if not self.undo_stack:
            messagebox.showinfo("Undo", "되돌릴 작업 히스토리가 없습니다.")
            return
        
        action = self.undo_stack.pop()
        action_type = action[0]
        
        if action_type == 'color':
            c_key, old_val = action[1], action[2]
            if old_val is None: self.custom_colors.pop(c_key, None)
            else: self.custom_colors[c_key] = old_val
                
        elif action_type == 'delete':
            key, unit_id = action[1], action[2]
            if key in self.deleted_units:
                self.deleted_units[key].discard(unit_id)
                
        self.refresh_current_charts()

    def refresh_current_charts(self):
        popup = tk.Toplevel(self); popup.title("Refreshing"); popup.transient(self); popup.grab_set()
        self.center_window(popup, 300, 80)
        tk.Label(popup, text="데이터 제어 상태 반영 중...", font=("Arial", 10)).pack(pady=25)
        p_bar = ttk.Progressbar(popup, mode='indeterminate')
        threading.Thread(target=self.render_analysis_worker, args=(popup, p_bar, tk.Label()), daemon=True).start()

    def update_lot_name(self, lot_key, new_name):
        if not new_name.strip(): return
        self.lot_display_names[lot_key] = new_name.strip()
        
        if lot_key in self.cached_plots:
            for lbl in self.cached_plots[lot_key]['labels']:
                lbl.config(text=f"■ [{new_name}] Lot Analysis")
            for fig, canvas in self.cached_plots[lot_key]['canvases']:
                for ax in fig.get_axes():
                    base = fig.__dict__.get('base_title', '')
                    ax.set_title(f"[{new_name}] {base}", fontsize=9, weight='bold')
                canvas.draw_idle()

    def export_to_pdf(self):
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF 리포트 파일", "*.pdf")])
        if not path: return
        try:
            with PdfPages(path) as pdf:
                for lot_key in sorted(self.cached_plots.keys()):
                    for fig, _ in self.cached_plots[lot_key]['canvases']:
                        pdf.savefig(fig, dpi=200, bbox_inches='tight')
            messagebox.showinfo("Success", "PDF 리포트 저장이 완료되었습니다!")
        except Exception as e:
            messagebox.showerror("Export Error", f"PDF 출력 오류:\n{str(e)}")

if __name__ == "__main__":
    DataAnalysisApp().mainloop()
