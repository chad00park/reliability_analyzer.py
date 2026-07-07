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
        self.title("Reliability Data Analyzer v3.2 - [Stable Version]")
        self.geometry("1450x950")
        self.center_window(self, 1450, 950) # 메인 창도 중앙 정렬
        
        self.raw_files_data = {}  
        self.parameter_list = []
        self.selected_parameters = []
        self.lot_groups = {}
        self.lot_display_names = {}
        self.cached_plots = {} 
        
        self.is_delta_mode = tk.BooleanVar(value=False)
        self.init_upload_menu()
        
    def center_window(self, win, w, h):
        """1. 모든 팝업 및 창을 화면 정중앙에 위치시키는 유틸리티 함수"""
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
        self.center_window(m, 300, 120) # 1. 모드 선택 팝업 중앙 정렬
        
        tk.Label(m, text="데이터 유형 선택", font=("Arial", 10, "bold")).pack(pady=10)
        f = tk.Frame(m); f.pack()
        tk.Button(f, text="Discrete", width=10, command=lambda: self.start_proc(files, "Discrete", m)).pack(side=tk.LEFT, padx=5)
        tk.Button(f, text="Module", width=10, command=lambda: self.start_proc(files, "Module", m)).pack(side=tk.LEFT, padx=5)

    def start_proc(self, files, mode, win):
        self.data_mode = mode; win.destroy(); self.process_files(files)

    def process_files(self, files):
        try:
            df_s = self.smart_read_csv_or_excel(files[0])
            p_idx, u_idx = None, None
            for i, r in df_s.iterrows():
                v = str(r.iloc[0]).strip().lower()
                if "parameter" in v: p_idx = i
                if "unit" in v: u_idx = i
            
            if p_idx is None or u_idx is None: raise ValueError("'Parameter'/'Unit' 행을 1열에서 찾을 수 없음")

            temp_data, all_p, self.lot_groups = {}, set(), {}
            for path in files:
                fname = os.path.basename(path)
                lot, ro, ro_n = self.parse_filename_info(fname)
                df = self.smart_read_csv_or_excel(path)
                
                d_start = max(p_idx, u_idx) + 1
                units = df.iloc[d_start:, 0].dropna().astype(str).tolist()
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
                    p_dict[pn] = {'unit': un, 'values': vals, 'units_map': units[:len(vals)]}
                    all_p.add(pn)
                
                temp_data[fname] = {'lot': lot, 'ro': ro, 'ro_num': ro_n, 'params': p_dict}
                if lot not in self.lot_groups: self.lot_groups[lot] = []
                self.lot_groups[lot].append(fname)

            self.parameter_list = sorted(list(all_p))
            if len(self.parameter_list) > 200: raise ValueError("Parameter 200개 초과")
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

        tk.Label(t, text="Parameter Selector (Ctrl/Shift 키로 다중 선택 가능):", font=("Arial", 11, "bold"), bg="#f4f4f4").pack(anchor="w")
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
        self.canvas.bind_all("<Button-4>", self._on_mouse_wheel)
        self.canvas.bind_all("<Button-5>", self._on_mouse_wheel)
        
        self.start_async_render()

    def _on_mouse_wheel(self, event):
        if event.num == 4: self.canvas.yview_scroll(-1, "units")
        elif event.num == 5: self.canvas.yview_scroll(1, "units")
        else: self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def start_async_render(self):
        selections = self.param_listbox.curselection()
        sel_items = [self.param_listbox.get(i) for i in selections]
        
        if "★ 전체 선택" in sel_items: self.selected_parameters = self.parameter_list.copy()
        else: self.selected_parameters = [v for v in sel_items if v != "★ 전체 선택"]
            
        if not self.selected_parameters: return
        
        # 팝업 생성 및 중앙 정렬 (메인 스레드에서 즉시 실행)
        popup = tk.Toplevel(self)
        popup.title("Processing")
        popup.transient(self); popup.grab_set()
        self.center_window(popup, 350, 120) # 1. 진행률 팝업 중앙 정렬
        
        tk.Label(popup, text="신뢰성 데이터를 실시간 분석 중입니다...", font=("Arial", 10, "bold")).pack(pady=10)
        p_bar = ttk.Progressbar(popup, length=280, mode='determinate'); p_bar.pack(pady=5)
        lbl_status = tk.Label(popup, text="0%", font=("Arial", 9)); lbl_status.pack()
        
        # 순수 데이터 정제 연산만 안전하게 백그라운드 스레드로 실행
        threading.Thread(target=self.render_analysis_worker, args=(popup, p_bar, lbl_status), daemon=True).start()

    def render_analysis_worker(self, popup, p_bar, lbl_status):
        """[Termination 원인 해결]: 무거운 수학 연산 데이터 추출만 스레드에서 수행"""
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
                for f_idx, filename in enumerate(lot_files):
                    if param not in self.raw_files_data[filename]['params']: continue
                    p_info = self.raw_files_data[filename]['params'][param]
                    ro_lbl = self.raw_files_data[filename]['ro']
                    
                    px, py, pc = [], [], []
                    for ux, uy in zip(p_info['units_map'], p_info['values']):
                        if uy is None or np.isnan(uy): continue
                        val_to_plot = uy
                        if self.is_delta_mode.get():
                            if ux in initial_vals: val_to_plot = 100 * (uy - initial_vals[ux]) / initial_vals[ux]
                            else: continue
                        
                        px.append(str(ux)); py.append(val_to_plot)
                        pc.append(base_colors[f_idx % len(base_colors)])

                    if px:
                        lines_dataset.append((px, py, pc, ro_lbl, base_colors[f_idx % len(base_colors)]))
                
                display_unit = "%" if self.is_delta_mode.get() else unit_str
                prepared_data.append(('plot', lot, {
                    'base_title': f"{param} ({display_unit})",
                    'dataset': lines_dataset
                }))
                
                current_step += 1
                pct = int((current_step / total_steps) * 100)
                # 메인스레드 UI 프로그레스 바 업데이트 요청
                self.after(0, lambda p=pct: [p_bar.config(value=p), lbl_status.config(text=f"{p}%")])

            # Box Plots 데이터 가공
            prepared_data.append(('start_box_grid', lot, None))
            for param in self.selected_parameters:
                b_data, a_labels, b_cols, stats = [], [], [], []
                for f_idx, fn in enumerate(lot_files):
                    if param in self.raw_files_data[fn]['params']:
                        vals = [v for v in self.raw_files_data[fn]['params'][param]['values'] if v is not None and not np.isnan(v)]
                        if vals:
                            b_data.append(vals); a_labels.append(self.raw_files_data[fn]['ro'])
                            b_cols.append(base_colors[f_idx % len(base_colors)])
                            stats.append(f"[{self.raw_files_data[fn]['ro']}]\nAvg:{np.mean(vals):.1f} Std:{np.std(vals):.1f}")
                if not b_data: continue

                prepared_data.append(('box_plot', lot, {
                    'base_title': f"{param} Dist",
                    'b_data': b_data, 'a_labels': a_labels, 'b_cols': b_cols, 'stats': stats
                }))

        # 연산이 완료되면 GUI 생성 메인스레드로 데이터를 토스하여 렌더링하도록 유도
        self.after(0, lambda: self.execute_ui_rendering(prepared_data, popup))

    def execute_ui_rendering(self, commands, popup):
        """[Termination 원인 해결]: 캔버스 및 피겨 생성은 오직 자식 스레드가 아닌 안전한 메인 스레드에서만 수행"""
        for w in self.scrollable_frame.winfo_children(): w.destroy()
        
        self.cached_plots = {} 
        current_frame = None
        grid_idx = 0
        box_frame = None
        box_idx = 0
        
        for cmd_type, lot_key, meta in commands:
            if cmd_type == 'title':
                header_f = tk.Frame(self.scrollable_frame, bg="#eaf2f8", pady=6)
                header_f.pack(fill=tk.X, padx=10, pady=5)
                
                lbl = tk.Label(header_f, text=f"■ [{self.lot_display_names[lot_key]}] Lot Analysis", font=("Arial", 13, "bold"), fg="#1e3799", bg="#eaf2f8")
                lbl.pack(side=tk.LEFT, padx=10)
                
                rename_f = tk.Frame(header_f, bg="#eaf2f8")
                rename_f.pack(side=tk.RIGHT, padx=15)
                tk.Label(rename_f, text="Lot명 커스텀:", font=("Arial", 9), bg="#eaf2f8").pack(side=tk.LEFT, padx=2)
                
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
                fig_h = 2.5 if self.data_mode == "Module" else 2.0
                fig, ax = plt.subplots(figsize=(fig_w, fig_h))
                
                # 가공해 둔 순수 데이터 셋으로 매플롯 그리기 진행
                for px, py, pc, ro_lbl, b_col in meta['dataset']:
                    ax.plot(px, py, color=b_col, alpha=0.5, zorder=1)
                    ax.scatter(px, py, color=pc, s=35, label=ro_lbl, zorder=3)
                
                fig.__dict__['base_title'] = meta['base_title']
                ax.set_title(f"[{self.lot_display_names[lot_key]}] {meta['base_title']}", fontsize=9, weight='bold')
                ax.grid(True, linestyle=":", alpha=0.5)
                ax.legend(loc="upper right", fontsize=7)
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

        # 2. 모든 데이터 시각화 정렬이 끝나면 팝업을 수동 개입 없이 자동 해제(Destroy)
        if popup: 
            popup.grab_release()
            popup.destroy()

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

if __name__ == "__main__":
    DataAnalysisApp().mainloop()
