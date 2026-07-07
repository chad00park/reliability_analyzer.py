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
        self.title("Reliability Data Analyzer v3.5 - [Structured PDF Report]")
        self.geometry("1450x950")
        self.center_window(self, 1450, 950)
        
        self.raw_files_data = {}  
        self.parameter_list = []
        self.selected_parameters = []
        self.lot_groups = {}
        self.lot_display_names = {}
        
        # 렌더링에 사용된 원본 matplotlib Figure 인스턴스들을 격자 구조 그대로 추적하기 위한 데이터 저장소
        self.rendering_layout_cache = {} # {lot_key: [ {'type': 'line'/'box', 'figs': [fig1, fig2, ...]} ]}
        
        # 인터랙티브 데이터 제어 상태 관리
        self.custom_colors = {}   
        self.deleted_units = {}    
        self.undo_stack = []       
        
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
            df_s = self.smart_read_csv_or_excel(files[0])
            p_idx, u_idx, sample_start_row = None, None, None
            
            # 2. 1열 전체를 탐색하며 파라미터, 유닛, 샘플 단어의 위치 추적
            for i, r in df_s.iterrows():
                val_first_col = str(r.iloc[0]).strip().lower().replace(" ", "")
                if "parameter" in val_first_col: p_idx = i
                if "unit" in val_first_col: u_idx = i
                if "sample" in val_first_col: sample_start_row = i

            if p_idx is None or u_idx is None: 
                raise ValueError("'Parameter' 혹은 'Unit' 행을 데이터 파일 1열에서 식별하지 못했습니다.")
            if sample_start_row is None:
                raise ValueError("1열에서 시료 번호의 시작점을 알리는 'sample' 단어를 찾을 수 없습니다.")

            temp_data, all_p, self.lot_groups = {}, set(), {}
            
            for path in files:
                fname = os.path.basename(path)
                lot, ro, ro_n = self.parse_filename_info(fname)
                df = self.smart_read_csv_or_excel(path)
                
                # 2. 'sample' 행의 다음 행부터 존재하는 아래 방향의 데이터를 시료 고유 목록(X축 눈금)으로 매핑
                units = df.iloc[sample_start_row + 1:, 0].dropna().astype(str).tolist()
                
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
                    
                    # 2. 각 파라미터 열(Column)에 나열된 시료들의 관측 데이터 매칭 구조 최적화
                    vals = pd.to_numeric(df.iloc[sample_start_row + 1:, c_idx + 1], errors='coerce').tolist()
                    vals = vals[:len(units)]
                    
                    if all(v is None or np.isnan(v) for v in vals): continue
                    
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
        tk.Button(ctrl_f, text="↩ 되돌리기 (Undo)", font=("Arial", 9, "bold"), bg="#7f8c8d", fg="white", command=self.perform_undo).pack(side=tk.LEFT, padx=5)
        
        # 1. 프로그램 뷰의 레이아웃 배열 구조 그대로 PDF 저장을 지원하는 레포트 버튼
        tk.Button(ctrl_f, text="📄 구조화된 PDF 리포트 저장", font=("Arial", 9, "bold"), bg="#c0392b", fg="white", command=self.export_to_pdf).pack(side=tk.LEFT, padx=5)

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
                        if str(ux) in del_set: continue  
                        
                        val_to_plot = uy
                        if self.is_delta_mode.get():
                            if ux in initial_vals: val_to_plot = 100 * (uy - initial_vals[ux]) / initial_vals[ux]
                            else: continue
                        
                        px.append(str(ux))
                        py.append(val_to_plot)
                        punit.append(str(ux))
                        
                        c_key = (lot, param, str(ux))
                        if c_key in self.custom_colors: pc.append(self.custom_colors[c_key])
                        else: pc.append(base_colors[f_idx % len(base_colors)])

                    if px: lines_dataset.append((px, py, pc, punit, ro_lbl, base_colors[f_idx % len(base_colors)]))
                
                display_unit = "%" if self.is_delta_mode.get() else unit_str
                prepared_data.append(('plot', lot, {
                    'param_name': param,
                    'base_title': f"{param} ({display_unit})",
                    'dataset': lines_dataset
                }))
                
                current_step += 1
                pct = int((current_step / total_steps) * 100)
                self.after(0, lambda p=pct: [p_bar.config(value=p), lbl_status.config(text=f"{p}%")])

            # Box Plots 데이터 연산
            prepared_data.append(('start_box_grid', lot, None))
            for param in self.selected_parameters:
                b_data, a_labels, b_cols, stats = [], [], [], []
                del_set = self.deleted_units.get((lot, param), set())

                for f_idx, fn in enumerate(lot_files):
                    if param in self.raw_files_data[fn]['params']:
                        p_info = self.raw_files_data[fn]['params'][param]
                        vals = [uy for ux, uy in zip(p_info['units_map'], p_info['values']) if uy is not None and not np.isnan(uy) and str(ux) not in del_set]
                                
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
        
        self.rendering_layout_cache = {} 
        current_frame, box_frame = None, None
        grid_idx, box_idx = 0, 0
        
        for cmd_type, lot_key, meta in commands:
            if lot_key not in self.rendering_layout_cache:
                self.rendering_layout_cache[lot_key] = []

            if cmd_type == 'title':
                header_f = tk.Frame(self.scrollable_frame, bg="#eaf2f8", pady=6)
                header_f.pack(fill=tk.X, padx=10, pady=5)
                
                lbl = tk.Label(header_f, text=f"■ [{self.lot_display_names[lot_key]}] Lot Analysis", font=("Arial", 13, "bold"), fg="#1e3799", bg="#eaf2f8")
                lbl.pack(side=tk.LEFT, padx=10)
                
                rename_f = tk.Frame(header_f, bg="#eaf2f8")
                rename_f.pack(side=tk.RIGHT, padx=15)
                tk.Label(rename_f, text="해당 Lot 명칭 변경:", font=("Arial", 9), bg="#eaf2f8").pack(side=tk.LEFT, padx=2)
                
                ent = tk.Entry(rename_f, width=15, font=("Arial", 9))
                ent.insert(0, self.lot_display_names[lot_key])
                ent.pack(side=tk.LEFT, padx=5)
                
                btn = tk.Button(rename_f, text="변경", font=("Arial", 8, "bold"), bg="#546e7a", fg="white",
                                command=lambda l=lot_key, e=ent: self.update_lot_name(l, e.get()))
                btn.pack(side=tk.LEFT)
                
            elif cmd_type == 'start_grid':
                current_frame = tk.Frame(self.scrollable_frame)
                current_frame.pack(fill=tk.X, padx=15, pady=5)
                for c in range(3): current_frame.grid_columnconfigure(c, weight=1)
                grid_idx = 0
                self.rendering_layout_cache[lot_key].append({'type': 'line', 'figs': []})
                
            elif cmd_type == 'plot':
                if self.data_mode == "Discrete" and (not self.rendering_layout_cache[lot_key] or self.rendering_layout_cache[lot_key][-1]['type'] != 'line'):
                    self.rendering_layout_cache[lot_key].append({'type': 'line', 'figs': []})

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
                self.rendering_layout_cache[lot_key][-1]['figs'].append(fig)
                
            elif cmd_type == 'start_box_grid':
                box_frame = tk.Frame(self.scrollable_frame, bg="#f9f9f9")
                box_frame.pack(fill=tk.X, padx=15, pady=10)
                for c in range(4): box_frame.grid_columnconfigure(c, weight=1)
                box_idx = 0
                self.rendering_layout_cache[lot_key].append({'type': 'box', 'figs': []})
                
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
                
                self.rendering_layout_cache[lot_key][-1]['figs'].append(fig)

        if popup: 
            popup.grab_release(); popup.destroy()

    def on_chart_point_clicked(self, event):
        scatter = event.artist
        if 'metadata' not in scatter.__dict__: return
        
        meta = scatter.__dict__['metadata']
        ind = event.ind[0]
        
        lot = meta['lot']
        param = meta['param']
        unit_id = meta['units'][ind]
        ro_info = meta['ro']
        
        m = tk.Toplevel(self); m.title("Interactive Data Editor"); m.geometry("450x180")
        self.center_window(m, 450, 180); m.transient(self); m.grab_set()
        
        tk.Label(m, text=f"선택한 시료 번호: {unit_id} ({ro_info})", font=("Arial", 11, "bold"), fg="#111111").pack(pady=10)
        color_section = tk.LabelFrame(m, text="원하는 변경 색상 선택", font=("Arial", 9))
        color_section.pack(fill=tk.X, padx=15, pady=5)
        
        distinct_palette = [("🔴 빨강", "#e74c3c"), ("🔵 군청", "#0a3d62"), ("🟢 연두", "#2ed573"), ("🟣 보라", "#8854d0"), ("🟠 주황", "#fa8231")]
        for text, hex_code in distinct_palette:
            btn = tk.Button(color_section, text=text, font=("Arial", 8, "bold"), bg=hex_code, fg="white", padx=4,
                            command=lambda l=lot, p=param, u=unit_id, c=hex_code: [m.destroy(), self.apply_point_color(l, p, u, c)])
            btn.pack(side=tk.LEFT, expand=True, padx=2, pady=5)
            
        action_f = tk.Frame(m); action_f.pack(pady=10)
        tk.Button(action_f, text="🗑️ 해당 시료 데이터 삭제 (Box연동)", bg="#2c3e50", fg="white", font=("Arial", 9, "bold"),
                  command=lambda: [m.destroy(), self.delete_target_unit(lot, param, unit_id)]).pack(side=tk.LEFT, padx=10)
        tk.Button(action_f, text="창 닫기", command=m.destroy).pack(side=tk.LEFT, padx=10)

    def apply_point_color(self, lot, param, unit_id, chosen_color):
        c_key = (lot, param, unit_id)
        old_color = self.custom_colors.get(c_key, None)
        self.undo_stack.append(('color', c_key, old_color))
        self.custom_colors[c_key] = chosen_color
        self.refresh_current_charts()

    def delete_target_unit(self, lot, param, unit_id):
        key = (lot, param)
        if key not in self.deleted_units: self.deleted_units[key] = set()
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
            if key in self.deleted_units: self.deleted_units[key].discard(unit_id)
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
        self.refresh_current_charts()

    def export_to_pdf(self):
        """1. 프로그램 내부 레이아웃 배열 형태(가로 N단 분할 Grid) 구조 그대로 단 한 치의 틀어짐 없이 PDF 페이지로 인쇄"""
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF 리포트 파일", "*.pdf")])
        if not path: return
        
        try:
            with PdfPages(path) as pdf:
                for lot_key in sorted(self.rendering_layout_cache.keys()):
                    blocks = self.rendering_layout_cache[lot_key]
                    
                    for block in blocks:
                        figs_list = block['figs']
                        if not figs_list: continue
                        
                        # 격자 레이아웃 구조체 정의 정보 캡처
                        if block['type'] == 'line':
                            cols = 3 if self.data_mode == "Module" else 1
                        else: # box_plot
                            cols = 4
                            
                        rows = int(np.ceil(len(figs_list) / cols))
                        
                        # 1. 화면 배열과 동일한 격자 스케일 크기를 지닌 PDF용 캔버스 동적 빌드
                        combined_fig, axes = plt.subplots(rows, cols, figsize=(cols * 4.5, rows * 3.2), squeeze=False)
                        
                        # 매플롯 레이아웃을 순회하며 개별 축(Axes)의 그래픽 데이터 그대로 이식 복사
                        for idx, src_fig in enumerate(figs_list):
                            r_idx = idx // cols
                            c_idx = idx % cols
                            target_ax = axes[r_idx, c_idx]
                            
                            src_ax = src_fig.get_axes()[0]
                            
                            # 선(Line) 및 포인트 그래픽 노드 완벽 카피 이식
                            for line in src_ax.get_lines():
                                target_ax.plot(line.get_xdata(), line.get_ydata(), color=line.get_color(), alpha=line.get_alpha(), zorder=line.get_zorder())
                            for collection in src_ax.collections:
                                paths = collection.get_paths()
                                offsets = collection.get_offsets()
                                if len(offsets) > 0:
                                    x_data = [o[0] for o in offsets]
                                    y_data = [o[1] for o in offsets]
                                    target_ax.scatter(src_ax.get_xticks()[0:len(x_data)] if block['type']=='box' else x_data, y_data, 
                                                      color=collection.get_facecolors(), s=collection.get_sizes(), zorder=collection.get_zorder())
                            
                            # 박스 플롯 컴포넌트 복사 보완
                            for patch in src_ax.patches:
                                target_ax.add_patch(plt.Rectangle((patch.get_x(), patch.get_y()), patch.get_width(), patch.get_height(), 
                                                                  facecolor=patch.get_facecolor(), alpha=patch.get_alpha()))
                                
                            # X/Y축 눈금 명칭 정밀 일치 배정
                            target_ax.set_title(src_ax.get_title(), fontsize=8, weight='bold')
                            target_ax.set_xticks(src_ax.get_xticks())
                            target_ax.set_xticklabels([t.get_text() for t in src_ax.get_xticklabels()], fontsize=7, rotation=15 if block['type']=='line' else 0)
                            target_ax.grid(True, linestyle=":", alpha=0.5)
                            
                            # 레전드 박스 그대로 유지 복사
                            src_legend = src_ax.get_legend()
                            if src_legend:
                                labels = [t.get_text() for t in src_legend.get_texts()]
                                target_ax.legend(labels, loc="best", fontsize=6)
                                
                        # 남은 빈 그리드 영역 축 숨김 처리
                        for idx in range(len(figs_list), rows * cols):
                            axes[idx // cols, idx % cols].axis('off')
                            
                        plt.tight_layout()
                        pdf.savefig(combined_fig, dpi=180, bbox_inches='tight')
                        plt.close(combined_fig)
                        
            messagebox.showinfo("Success", "화면 격자 구조 배열 그대로 고해상도 PDF 보고서 저장이 완료되었습니다!")
        except Exception as e:
            messagebox.showerror("Export Error", f"PDF 통합 출력 중 예외 에러가 발생했습니다:\n{str(e)}")

if __name__ == "__main__":
    DataAnalysisApp().mainloop()
